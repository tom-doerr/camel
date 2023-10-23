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

from typing import Any, List, Optional, Tuple

from camel.memory.base import BaseMemory, MemoryRecord
from camel.memory.context_creator.base import BaseContextCreator, ContextRecord
from camel.messages import OpenAIMessage
from camel.storage.dict_storage.base import BaseDictStorage
from camel.storage.dict_storage.in_memory import InMemoryDictStorage
from camel.typing import OpenAIBackendRole


class ChatHistoryMemory(BaseMemory):
    r"""
    An implementation of the :obj:`BaseMemory` abstract base class for
    maintaining a record of chat histories.

    This memory class helps manage conversation histories with a designated
    storage mechanism, either provided by the user or using a default
    in-memory storage. It offers a windowed approach to retrieving chat
    histories, allowing users to specify how many recent messages they'd
    like to fetch.

    `ChatHistoryMemory` requires messages to be stored with certain
    metadata (e.g., `role_at_backend`) to maintain consistency and validate
    the chat history.

    Args:
        context_creator (BaseContextCreator): A context creator contianing
            the context limit and the message pruning strategy.
        storage (BaseDictStorage, optional): A storage mechanism for storing
            chat history. (default: :obj:`InMemoryDictStorage()`)
        window_size (int, optional): Specifies the number of recent chat
            messages to retrieve. If not provided, the entire chat history
            will be retrieved. (default: :obj:`None`)
    """

    def __init__(
        self,
        context_creator: BaseContextCreator,
        storage: Optional[BaseDictStorage] = None,
        window_size: Optional[int] = None,
    ) -> None:
        self.context_creator = context_creator
        self.storage = storage or InMemoryDictStorage()
        self.window_size = window_size

    def get_context(self) -> Tuple[List[OpenAIMessage], int]:
        r"""
        Gets chat context with proper size for a LLM from the memory based on
        the window size or fetches the entire chat history if no window size is
        specified.

        Returns:
            (List[OpenAIMessage], int): A tuple containing the constructed
                context in OpenAIMessage format and the total token count.
        Raises:
            ValueError: If the memory is empty or if the first message in the
                memory is not a system message.
        """
        record_dicts = self.storage.load()
        if len(record_dicts) == 0:
            raise ValueError("The ChatHistoryMemory is empty.")

        system_record = MemoryRecord.from_dict(record_dicts[0])
        if system_record.role_at_backend != OpenAIBackendRole.SYSTEM:
            raise ValueError(
                "The first record in ChatHistoryMemory should contain a system"
                " message.")
        chat_records: List[MemoryRecord] = []
        truncate_idx = 1 if self.window_size is None else -self.window_size
        for record_dict in record_dicts[truncate_idx:]:
            chat_records.append(MemoryRecord.from_dict(record_dict))

        output_records = []
        importance = 1.0
        for record in reversed(chat_records):
            importance *= 0.99
            output_records.append(ContextRecord(record, importance))
        output_records.append(ContextRecord(system_record, 1.0))
        output_records.reverse()
        return self.context_creator.create_context(output_records)

    def retrieve(self, condition: Any = None) -> List[MemoryRecord]:
        if condition is not None and condition.__class__ != list:
            raise ValueError("condition must be None or a list of indecies")
        record_dicts = self.storage.load()
        output_records = []
        if condition is None:
            output_records = [MemoryRecord.from_dict(r) for r in record_dicts]
        else:
            output_records = [
                MemoryRecord.from_dict(record_dicts[i]) for i in condition
            ]

        return output_records

    def write_records(self, records: List[MemoryRecord]) -> None:
        r"""
        Writes memory records to the memory. Additionally, performs validation
        checks on the messages.

        Args:
            msgs (List[MemoryRecord]): Memory records to be added to the
                memory.
        """
        stored_records = []
        for record in records:
            stored_records.append(record.to_dict())
        self.storage.save(stored_records)

    def clear(self) -> None:
        r"""
            Clears all chat messages from the memory.
        """
        self.storage.clear()
