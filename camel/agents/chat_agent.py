# =========== Copyright 2023 @ CAMEL-AI.org. All Rights Reserved. ===========
# Licensed under the Apache License, Version 2.0 (the “License”);
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an “AS IS” BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# =========== Copyright 2023 @ CAMEL-AI.org. All Rights Reserved. ===========
from __future__ import annotations

import json
import logging
from collections import defaultdict
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Tuple,
    Union,
)

from pydantic import BaseModel

from camel.agents.base import BaseAgent
from camel.configs import ChatGPTConfig
from camel.memories import (
    AgentMemory,
    ChatHistoryMemory,
    MemoryRecord,
    ScoreBasedContextCreator,
)
from camel.messages import BaseMessage, FunctionCallingMessage, OpenAIMessage
from camel.models import BaseModelBackend, ModelFactory
from camel.responses import ChatAgentResponse
from camel.types import (
    ChatCompletion,
    ChatCompletionChunk,
    ModelPlatformType,
    ModelType,
    OpenAIBackendRole,
    RoleType,
)
from camel.utils import (
    Constants,
    func_string_to_callable,
    get_model_encoding,
    get_pydantic_object_schema,
    json_to_function_code,
)

if TYPE_CHECKING:
    from openai import Stream

    from camel.terminators import ResponseTerminator
    from camel.toolkits import FunctionTool


logger = logging.getLogger(__name__)

# AgentOps decorator setting
try:
    import os

    if os.getenv("AGENTOPS_API_KEY") is not None:
        from agentops import track_agent
    else:
        raise ImportError
except (ImportError, AttributeError):
    from camel.utils import track_agent


class FunctionCallingRecord(BaseModel):
    r"""Historical records of functions called in the conversation.

    Attributes:
        func_name (str): The name of the function being called.
        args (Dict[str, Any]): The dictionary of arguments passed to
            the function.
        result (Any): The execution result of calling this function.
    """

    func_name: str
    args: Dict[str, Any]
    result: Any

    def __str__(self) -> str:
        r"""Overridden version of the string function.

        Returns:
            str: Modified string to represent the function calling.
        """
        return (
            f"Function Execution: {self.func_name}\n"
            f"\tArgs: {self.args}\n"
            f"\tResult: {self.result}"
        )

    def as_dict(self) -> dict[str, Any]:
        return self.model_dump()


@track_agent(name="ChatAgent")
class ChatAgent(BaseAgent):
    r"""Class for managing conversations of CAMEL Chat Agents.

    Args:
        system_message (BaseMessage): The system message for the chat agent.
        model (BaseModelBackend, optional): The model backend to use for
            generating responses. (default: :obj:`OpenAIModel` with
            `GPT_4O_MINI`)
        memory (AgentMemory, optional): The agent memory for managing chat
            messages. If `None`, a :obj:`ChatHistoryMemory` will be used.
            (default: :obj:`None`)
        message_window_size (int, optional): The maximum number of previous
            messages to include in the context window. If `None`, no windowing
            is performed. (default: :obj:`None`)
        token_limit (int, optional): The maximum number of tokens in a context.
            The context will be automatically pruned to fulfill the limitation.
            If `None`, it will be set according to the backend model.
            (default: :obj:`None`)
        output_language (str, optional): The language to be output by the
            agent. (default: :obj:`None`)
        tools (List[FunctionTool], optional): List of available
            :obj:`FunctionTool`. (default: :obj:`None`)
        response_terminators (List[ResponseTerminator], optional): List of
            :obj:`ResponseTerminator` bind to one chat agent.
            (default: :obj:`None`)
    """

    def __init__(
        self,
        system_message: BaseMessage,
        model: Optional[BaseModelBackend] = None,
        memory: Optional[AgentMemory] = None,
        message_window_size: Optional[int] = None,
        token_limit: Optional[int] = None,
        output_language: Optional[str] = None,
        tools: Optional[List[FunctionTool]] = None,
        response_terminators: Optional[List[ResponseTerminator]] = None,
    ) -> None:
        self.orig_sys_message: BaseMessage = system_message
        self.system_message = system_message
        self.role_name: str = system_message.role_name
        self.role_type: RoleType = system_message.role_type
        self.model_backend: BaseModelBackend = (
            model
            if model is not None
            else ModelFactory.create(
                model_platform=ModelPlatformType.OPENAI,
                model_type=ModelType.GPT_4O_MINI,
                model_config_dict=ChatGPTConfig().as_dict(),
            )
        )
        self.output_language: Optional[str] = output_language
        if self.output_language is not None:
            self.set_output_language(self.output_language)

        self.model_type: ModelType = self.model_backend.model_type

        self.func_dict: Dict[str, Callable] = {}
        if tools is not None:
            for func in tools:
                self.func_dict[func.get_function_name()] = func.func

        self.model_config_dict = self.model_backend.model_config_dict

        self.model_token_limit = token_limit or self.model_backend.token_limit
        context_creator = ScoreBasedContextCreator(
            self.model_backend.token_counter,
            self.model_token_limit,
        )
        self.memory: AgentMemory = memory or ChatHistoryMemory(
            context_creator, window_size=message_window_size
        )

        self.terminated: bool = False
        self.response_terminators = response_terminators or []
        self.init_messages()

    def reset(self):
        r"""Resets the :obj:`ChatAgent` to its initial state and returns the
        stored messages.

        Returns:
            List[BaseMessage]: The stored messages.
        """
        self.terminated = False
        self.init_messages()
        for terminator in self.response_terminators:
            terminator.reset()

    @property
    def system_message(self) -> BaseMessage:
        r"""The getter method for the property :obj:`system_message`.

        Returns:
            BaseMessage: The system message of this agent.
        """
        return self._system_message

    @system_message.setter
    def system_message(self, message: BaseMessage):
        r"""The setter method for the property :obj:`system_message`.

        Args:
            message (BaseMessage): The message to be set as the
                new system message of this agent.
        """
        self._system_message = message

    def is_tools_added(self) -> bool:
        r"""Whether OpenAI function calling is enabled for this agent.

        Returns:
            bool: Whether OpenAI function calling is enabled for this
                agent, determined by whether the dictionary of tools
                is empty.
        """
        return len(self.func_dict) > 0

    def update_memory(
        self, message: BaseMessage, role: OpenAIBackendRole
    ) -> None:
        r"""Updates the agent memory with a new message.

        Args:
            message (BaseMessage): The new message to add to the stored
                messages.
            role (OpenAIBackendRole): The backend role type.
        """
        self.memory.write_record(
            MemoryRecord(message=message, role_at_backend=role)
        )

    def set_output_language(self, output_language: str) -> BaseMessage:
        r"""Sets the output language for the system message. This method
        updates the output language for the system message. The output
        language determines the language in which the output text should be
        generated.

        Args:
            output_language (str): The desired output language.

        Returns:
            BaseMessage: The updated system message object.
        """
        self.output_language = output_language
        content = self.orig_sys_message.content + (
            "\nRegardless of the input language, "
            f"you must output text in {output_language}."
        )
        self.system_message = self.system_message.create_new_instance(content)
        return self.system_message

    def get_info(
        self,
        id: Optional[str],
        usage: Optional[Dict[str, int]],
        termination_reasons: List[str],
        num_tokens: int,
        tool_calls: List[FunctionCallingRecord],
    ) -> Dict[str, Any]:
        r"""Returns a dictionary containing information about the chat session.

        Args:
            id (str, optional): The ID of the chat session.
            usage (Dict[str, int], optional): Information about the usage of
                the LLM model.
            termination_reasons (List[str]): The reasons for the termination
                of the chat session.
            num_tokens (int): The number of tokens used in the chat session.
            tool_calls (List[FunctionCallingRecord]): The list of function
                calling records, containing the information of called
                tools.

        Returns:
            Dict[str, Any]: The chat session information.
        """
        return {
            "id": id,
            "usage": usage,
            "termination_reasons": termination_reasons,
            "num_tokens": num_tokens,
            "tool_calls": tool_calls,
        }

    def init_messages(self) -> None:
        r"""Initializes the stored messages list with the initial system
        message.
        """
        system_record = MemoryRecord(
            message=self.system_message,
            role_at_backend=OpenAIBackendRole.SYSTEM,
        )
        self.memory.clear()
        self.memory.write_record(system_record)

    def record_message(self, message: BaseMessage) -> None:
        r"""Records the externally provided message into the agent memory as if
        it were an answer of the :obj:`ChatAgent` from the backend. Currently,
        the choice of the critic is submitted with this method.

        Args:
            message (BaseMessage): An external message to be recorded in the
                memory.
        """
        self.update_memory(message, OpenAIBackendRole.ASSISTANT)

    def step(
        self,
        input_message: BaseMessage,
        output_schema: Optional[BaseModel] = None,
    ) -> ChatAgentResponse:
        r"""Performs a single step in the chat session by generating a response
        to the input message.

        Args:
            input_message (BaseMessage): The input message to the agent.
                Its `role` field that specifies the role at backend may be
                either `user` or `assistant` but it will be set to `user`
                anyway since for the self agent any incoming message is
                external.
            output_schema (Optional[BaseModel]): An optional pydantic model
                that includes value types and field descriptions used to
                generate a structured response by LLM. This schema helps
                in defining the expected output format.

        Returns:
            ChatAgentResponse: A struct containing the output messages,
                a boolean indicating whether the chat session has terminated,
                and information about the chat session.
        """
        self.update_memory(input_message, OpenAIBackendRole.USER)

        output_messages: List[BaseMessage]
        info: Dict[str, Any]
        tool_calls: List[FunctionCallingRecord] = []
        while True:
            # Format messages and get the token number
            openai_messages: Optional[List[OpenAIMessage]]

            try:
                openai_messages, num_tokens = self.memory.get_context()
            except RuntimeError as e:
                return self.step_token_exceed(
                    e.args[1], tool_calls, "max_tokens_exceeded"
                )
            # use structed output response without tools
            # If the user provides the output_schema parameter and does not
            # specify the use of tools, then in the model config of the
            # chatgent, call the model specified by tools with
            # return_json_response of FunctionTool format, and return a
            # structured response with the user-specified output schema.
            if output_schema is not None and len(self.func_dict) == 0:
                self._add_output_schema_to_tool_list(output_schema)

            (
                response,
                output_messages,
                finish_reasons,
                usage_dict,
                response_id,
            ) = self._step_model_response(openai_messages, num_tokens)

            if (
                self.is_tools_added()
                and isinstance(response, ChatCompletion)
                and response.choices[0].message.tool_calls is not None
            ):
                # Tools added for function calling and not in stream mode

                tool_calls, func_assistant_msg, func_result_msg = (
                    self._add_tools_for_func_call(response, tool_calls)
                )

                # Update the messages
                self.update_memory(
                    func_assistant_msg, OpenAIBackendRole.ASSISTANT
                )
                self.update_memory(func_result_msg, OpenAIBackendRole.FUNCTION)

            else:
                # If the user specifies tools, it is necessary to wait for the
                # model to complete all tools' calls. Finally, use the
                # generated response as the input for the structure,
                # simultaneously calling the return_json_response function.
                # Call the model again with return_json_response in the format
                # of FunctionTool as the last tool, returning a structured
                # response with the user-specified output schema.
                if output_schema is not None and all(
                    record.func_name
                    != Constants.FUNC_NAME_FOR_STRUCTURE_OUTPUT
                    for record in tool_calls
                ):
                    self._add_output_schema_to_tool_list(output_schema)

                    (
                        response,
                        output_messages,
                        finish_reasons,
                        usage_dict,
                        response_id,
                    ) = self._step_model_response(openai_messages, num_tokens)

                    if isinstance(response, ChatCompletion):
                        # Tools added for function calling and not in stream
                        # mode
                        tool_calls, func_assistant_msg, func_result_msg = (
                            self._add_tools_for_func_call(response, tool_calls)
                        )

                        # Update the messages
                        self.update_memory(
                            func_assistant_msg, OpenAIBackendRole.ASSISTANT
                        )
                        self.update_memory(
                            func_result_msg, OpenAIBackendRole.FUNCTION
                        )

                info = self._step_get_info(
                    output_messages,
                    finish_reasons,
                    usage_dict,
                    response_id,
                    tool_calls,
                    num_tokens,
                )
                break

        # if use structure response, set structure result as content of
        # BaseMessage
        if output_schema and self.model_type.is_openai:
            for base_message_item in output_messages:
                base_message_item.content = str(info['tool_calls'][-1].result)

        chat_agent_response = ChatAgentResponse(
            msgs=output_messages, terminated=self.terminated, info=info
        )

        # If the output result is single message, it will be
        # automatically added to the memory.
        if len(chat_agent_response.msgs) == 1:
            self.record_message(chat_agent_response.msg)
        else:
            logger.warning(
                "Multiple messages are available in `ChatAgentResponse`. "
                "Please manually run the `record_message` function to "
                "record the selected message."
            )
        return chat_agent_response

    async def step_async(
        self,
        input_message: BaseMessage,
        output_schema: Optional[BaseModel] = None,
    ) -> ChatAgentResponse:
        r"""Performs a single step in the chat session by generating a response
        to the input message. This agent step can call async function calls.

        Args:
            input_message (BaseMessage): The input message to the agent.
                Its `role` field that specifies the role at backend may be
                either `user` or `assistant` but it will be set to `user`
                anyway since for the self agent any incoming message is
                external.
            output_schema (Optional[BaseModel]): An optional pydantic model
                that includes value types and field descriptions used to
                generate a structured response by LLM. This schema helps
                in defining the expected output format.

        Returns:
            ChatAgentResponse: A struct containing the output messages,
                a boolean indicating whether the chat session has terminated,
                and information about the chat session.
        """
        self.update_memory(input_message, OpenAIBackendRole.USER)

        output_messages: List[BaseMessage]
        info: Dict[str, Any]
        tool_calls: List[FunctionCallingRecord] = []
        while True:
            # Format messages and get the token number
            openai_messages: Optional[List[OpenAIMessage]]

            try:
                openai_messages, num_tokens = self.memory.get_context()
            except RuntimeError as e:
                return self.step_token_exceed(
                    e.args[1], tool_calls, "max_tokens_exceeded"
                )
            if output_schema is not None:
                self._add_output_schema_to_tool_list(output_schema)

            (
                response,
                output_messages,
                finish_reasons,
                usage_dict,
                response_id,
            ) = self._step_model_response(openai_messages, num_tokens)

            if (
                self.is_tools_added()
                and isinstance(response, ChatCompletion)
                and response.choices[0].message.tool_calls is not None
            ):
                # Tools added for function calling and not in stream mode

                # Do function calling
                (
                    func_assistant_msg,
                    func_result_msg,
                    func_record,
                ) = await self.step_tool_call_async(response)

                # Update the messages
                self.update_memory(
                    func_assistant_msg, OpenAIBackendRole.ASSISTANT
                )
                self.update_memory(func_result_msg, OpenAIBackendRole.FUNCTION)

                # Record the function calling
                tool_calls.append(func_record)

            else:
                # use structed output response without tools
                if output_schema is not None and all(
                    record.func_name
                    != Constants.FUNC_NAME_FOR_STRUCTURE_OUTPUT
                    for record in tool_calls
                ):
                    self._add_output_schema_to_tool_list(output_schema)

                    (
                        response,
                        output_messages,
                        finish_reasons,
                        usage_dict,
                        response_id,
                    ) = self._step_model_response(openai_messages, num_tokens)

                    if isinstance(response, ChatCompletion):
                        # Tools added for function calling and not in stream
                        # mode
                        tool_calls, func_assistant_msg, func_result_msg = (
                            self._add_tools_for_func_call(response, tool_calls)
                        )

                        # Update the messages
                        self.update_memory(
                            func_assistant_msg, OpenAIBackendRole.ASSISTANT
                        )
                        self.update_memory(
                            func_result_msg, OpenAIBackendRole.FUNCTION
                        )

                # Function calling disabled or not a function calling
                info = self._step_get_info(
                    output_messages,
                    finish_reasons,
                    usage_dict,
                    response_id,
                    tool_calls,
                    num_tokens,
                )
                break

        # if use structure response, set structure result as content of
        # BaseMessage
        if output_schema and self.model_type.is_openai:
            for base_message_item in output_messages:
                base_message_item.content = str(info['tool_calls'][0].result)

        chat_agent_response = ChatAgentResponse(
            msgs=output_messages, terminated=self.terminated, info=info
        )

        # If the output result is single message, it will be
        # automatically added to the memory.
        if len(chat_agent_response.msgs) == 1:
            self.record_message(chat_agent_response.msg)
        else:
            logger.warning(
                "Multiple messages are presented in `chat_agent_response`. "
                "Please manually call the `record_message` function to "
                "record the chosen message."
            )

        return chat_agent_response

    def _add_tools_for_func_call(
        self,
        response: ChatCompletion,
        tool_calls: List[FunctionCallingRecord],
    ) -> tuple[
        List[FunctionCallingRecord],
        FunctionCallingMessage,
        FunctionCallingMessage,
    ]:
        r"""
        Handles adding tools for function calls based on the response.
        This method processes a function call within the chat completion
        response, and records the function call in the provided
        list of tool calls.
        Args:
            response (ChatCompletion): The response object from the chat
                completion.
            tool_calls (List[FunctionCallingRecord]): The list to record
                function calls.
        Returns:
            tuple: A tuple containing:
                - List[FunctionCallingRecord]: The updated list of function
                  call records.
                - FunctionCallingMessage: The assistant's message regarding the
                  function call.
                - FunctionCallingMessage: The result message of the function
                  call.
        """

        # Perform function calling
        func_assistant_msg, func_result_msg, func_record = self.step_tool_call(
            response
        )

        # Record the function call in the list of tool calls
        tool_calls.append(func_record)

        # Return updated tool calls list, assistant's message, and function
        # result message
        return tool_calls, func_assistant_msg, func_result_msg

    def _add_output_schema_to_tool_list(self, output_schema: BaseModel):
        r"""Handles the structured output response for OpenAI.
        This method processes the given output schema and integrates the
        resulting function into the tools for the OpenAI model configuration.
        Args:
            output_schema (BaseModel): The schema representing the expected
                output structure.
        """
        from camel.toolkits import FunctionTool

        # step 1 extract the output_schema info as json.
        schema_json = get_pydantic_object_schema(output_schema)

        # step 2 convert output schema json as callable string
        func_str = json_to_function_code(schema_json)

        # step 3 get callable function from string
        func_callable = func_string_to_callable(func_str)

        # step 4 add return_json_func into tools
        func = FunctionTool(func_callable)
        tools = [func]
        self.func_dict[func.get_function_name()] = func.func
        if self.model_type.is_openai:
            self.model_backend.model_config_dict = ChatGPTConfig(
                tools=tools
            ).as_dict()
        elif self.model_type.is_gemini:
            from camel.configs.gemini_config import GeminiConfig

            self.model_backend.model_config_dict = GeminiConfig(
                tools=tools
            ).as_dict()

    def _step_model_response(
        self,
        openai_messages: List[OpenAIMessage],
        num_tokens: int,
    ) -> tuple[
        Union[ChatCompletion, Stream],
        List[BaseMessage],
        List[str],
        Dict[str, int],
        str,
    ]:
        r"""Internal function for agent step model response."""
        # Obtain the model's response
        response = self.model_backend.run(openai_messages)

        if isinstance(response, ChatCompletion):
            output_messages, finish_reasons, usage_dict, response_id = (
                self.handle_batch_response(response)
            )
        else:
            output_messages, finish_reasons, usage_dict, response_id = (
                self.handle_stream_response(response, num_tokens)
            )
        return (
            response,
            output_messages,
            finish_reasons,
            usage_dict,
            response_id,
        )

    def _step_get_info(
        self,
        output_messages: List[BaseMessage],
        finish_reasons: List[str],
        usage_dict: Dict[str, int],
        response_id: str,
        tool_calls: List[FunctionCallingRecord],
        num_tokens: int,
    ) -> Dict[str, Any]:
        # Loop over responses terminators, get list of termination
        # tuples with whether the terminator terminates the agent
        # and termination reason
        termination = [
            terminator.is_terminated(output_messages)
            for terminator in self.response_terminators
        ]
        # Terminate the agent if any of the terminator terminates
        self.terminated, termination_reason = next(
            (
                (terminated, termination_reason)
                for terminated, termination_reason in termination
                if terminated
            ),
            (False, None),
        )
        # For now only retain the first termination reason
        if self.terminated and termination_reason is not None:
            finish_reasons = [termination_reason] * len(finish_reasons)

        info = self.get_info(
            response_id,
            usage_dict,
            finish_reasons,
            num_tokens,
            tool_calls,
        )
        return info

    def handle_batch_response(
        self, response: ChatCompletion
    ) -> Tuple[List[BaseMessage], List[str], Dict[str, int], str]:
        r"""

        Args:
            response (dict): Model response.

        Returns:
            tuple: A tuple of list of output `ChatMessage`, list of
                finish reasons, usage dictionary, and response id.
        """
        output_messages: List[BaseMessage] = []
        for choice in response.choices:
            chat_message = BaseMessage(
                role_name=self.role_name,
                role_type=self.role_type,
                meta_dict=dict(),
                content=choice.message.content or "",
            )
            output_messages.append(chat_message)
        finish_reasons = [
            str(choice.finish_reason) for choice in response.choices
        ]
        usage = (
            response.usage.model_dump() if response.usage is not None else {}
        )
        return (
            output_messages,
            finish_reasons,
            usage,
            response.id,
        )

    def handle_stream_response(
        self,
        response: Stream[ChatCompletionChunk],
        prompt_tokens: int,
    ) -> Tuple[List[BaseMessage], List[str], Dict[str, int], str]:
        r"""

        Args:
            response (dict): Model response.
            prompt_tokens (int): Number of input prompt tokens.

        Returns:
            tuple: A tuple of list of output `ChatMessage`, list of
                finish reasons, usage dictionary, and response id.
        """
        content_dict: defaultdict = defaultdict(lambda: "")
        finish_reasons_dict: defaultdict = defaultdict(lambda: "")
        output_messages: List[BaseMessage] = []
        response_id: str = ""
        # All choices in one response share one role
        for chunk in response:
            response_id = chunk.id
            for choice in chunk.choices:
                index = choice.index
                delta = choice.delta
                if delta.content is not None:
                    # When response has not been stopped
                    # Notice that only the first chunk_dict has the "role"
                    content_dict[index] += delta.content
                else:
                    finish_reasons_dict[index] = choice.finish_reason
                    chat_message = BaseMessage(
                        role_name=self.role_name,
                        role_type=self.role_type,
                        meta_dict=dict(),
                        content=content_dict[index],
                    )
                    output_messages.append(chat_message)
        finish_reasons = [
            finish_reasons_dict[i] for i in range(len(finish_reasons_dict))
        ]
        usage_dict = self.get_usage_dict(output_messages, prompt_tokens)
        return output_messages, finish_reasons, usage_dict, response_id

    def step_token_exceed(
        self,
        num_tokens: int,
        tool_calls: List[FunctionCallingRecord],
        termination_reason: str,
    ) -> ChatAgentResponse:
        r"""Return trivial response containing number of tokens and information
        of called functions when the number of tokens exceeds.

        Args:
            num_tokens (int): Number of tokens in the messages.
            tool_calls (List[FunctionCallingRecord]): List of information
                objects of functions called in the current step.
            termination_reason (str): String of termination reason.

        Returns:
            ChatAgentResponse: The struct containing trivial outputs and
                information about token number and called functions.
        """
        self.terminated = True
        output_messages: List[BaseMessage] = []

        info = self.get_info(
            None,
            None,
            [termination_reason],
            num_tokens,
            tool_calls,
        )

        return ChatAgentResponse(
            msgs=output_messages,
            terminated=self.terminated,
            info=info,
        )

    def step_tool_call(
        self,
        response: ChatCompletion,
    ) -> Tuple[
        FunctionCallingMessage, FunctionCallingMessage, FunctionCallingRecord
    ]:
        r"""Execute the function with arguments following the model's response.

        Args:
            response (Dict[str, Any]): The response obtained by calling the
                model.

        Returns:
            tuple: A tuple consisting of two obj:`FunctionCallingMessage`,
                one about the arguments and the other about the execution
                result, and a struct for logging information about this
                function call.
        """
        choice = response.choices[0]
        if choice.message.tool_calls is None:
            raise RuntimeError("Tool call is None")
        func_name = choice.message.tool_calls[0].function.name
        func = self.func_dict[func_name]

        args_str: str = choice.message.tool_calls[0].function.arguments
        args = json.loads(args_str)

        # Pass the extracted arguments to the indicated function
        try:
            result = func(**args)
        except Exception:
            raise ValueError(
                f"Execution of function {func.__name__} failed with "
                f"arguments being {args}."
            )

        assist_msg = FunctionCallingMessage(
            role_name=self.role_name,
            role_type=self.role_type,
            meta_dict=None,
            content="",
            func_name=func_name,
            args=args,
        )
        func_msg = FunctionCallingMessage(
            role_name=self.role_name,
            role_type=self.role_type,
            meta_dict=None,
            content="",
            func_name=func_name,
            result=result,
        )

        # Record information about this function call
        func_record = FunctionCallingRecord(
            func_name=func_name, args=args, result=result
        )
        return assist_msg, func_msg, func_record

    async def step_tool_call_async(
        self,
        response: ChatCompletion,
    ) -> Tuple[
        FunctionCallingMessage, FunctionCallingMessage, FunctionCallingRecord
    ]:
        r"""Execute the async function with arguments following the model's
        response.

        Args:
            response (Dict[str, Any]): The response obtained by calling the
                model.

        Returns:
            tuple: A tuple consisting of two obj:`FunctionCallingMessage`,
                one about the arguments and the other about the execution
                result, and a struct for logging information about this
                function call.
        """
        # Note that when function calling is enabled, `n` is set to 1.
        choice = response.choices[0]
        if choice.message.tool_calls is None:
            raise RuntimeError("Tool call is None")
        func_name = choice.message.tool_calls[0].function.name
        func = self.func_dict[func_name]

        args_str: str = choice.message.tool_calls[0].function.arguments
        args = json.loads(args_str)

        # Pass the extracted arguments to the indicated function
        try:
            result = await func(**args)
        except Exception:
            raise ValueError(
                f"Execution of function {func.__name__} failed with "
                f"arguments being {args}."
            )

        assist_msg = FunctionCallingMessage(
            role_name=self.role_name,
            role_type=self.role_type,
            meta_dict=None,
            content="",
            func_name=func_name,
            args=args,
        )
        func_msg = FunctionCallingMessage(
            role_name=self.role_name,
            role_type=self.role_type,
            meta_dict=None,
            content="",
            func_name=func_name,
            result=result,
        )

        # Record information about this function call
        func_record = FunctionCallingRecord(
            func_name=func_name, args=args, result=result
        )
        return assist_msg, func_msg, func_record

    def get_usage_dict(
        self, output_messages: List[BaseMessage], prompt_tokens: int
    ) -> Dict[str, int]:
        r"""Get usage dictionary when using the stream mode.

        Args:
            output_messages (list): List of output messages.
            prompt_tokens (int): Number of input prompt tokens.

        Returns:
            dict: Usage dictionary.
        """
        encoding = get_model_encoding(self.model_type.value_for_tiktoken)
        completion_tokens = 0
        for message in output_messages:
            completion_tokens += len(encoding.encode(message.content))
        usage_dict = dict(
            completion_tokens=completion_tokens,
            prompt_tokens=prompt_tokens,
            total_tokens=completion_tokens + prompt_tokens,
        )
        return usage_dict

    def __repr__(self) -> str:
        r"""Returns a string representation of the :obj:`ChatAgent`.

        Returns:
            str: The string representation of the :obj:`ChatAgent`.
        """
        return (
            f"ChatAgent({self.role_name}, {self.role_type}, {self.model_type})"
        )
