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
from typing import List, Union

from camel.retrievers import AutoRetriever
from camel.toolkits import FunctionTool
from camel.toolkits.base import BaseToolkit
from camel.types import StorageType


class RetrievalToolkit(BaseToolkit):
    r"""A class representing a toolkit for information retrieval.

    This class provides methods for retrieving information from a local vector
    storage system based on a specified query.
    """

    def information_retrieval(
        self, query: str, contents: Union[str, List[str]]
    ) -> str:
        r"""Retrieves information from a local vector storage based on the
        specified query. This function connects to a local vector storage
        system and retrieves relevant information by processing the input
        query. It is essential to use this function when the answer to a
        question requires external knowledge sources.

        Args:
            query (str): The question or query for which an answer is required.
            contents (Union[str, List[str]]): Local file paths, remote URLs or
                string contents.

        Returns:
            str: The information retrieved in response to the query, aggregated
                and formatted as a string.

        Example:
            # Retrieve information about CAMEL AI.
            information_retrieval(query = "what is CAMEL AI?",
                                contents="https://www.camel-ai.org/")
        """
        auto_retriever = AutoRetriever(
            vector_storage_local_path="camel/temp_storage",
            storage_type=StorageType.QDRANT,
        )

        retrieved_info = auto_retriever.run_vector_retriever(
            query=query, contents=contents, top_k=3
        )
        return str(retrieved_info)

    def get_tools(self) -> List[FunctionTool]:
        r"""Returns a list of FunctionTool objects representing the
        functions in the toolkit.

        Returns:
            List[FunctionTool]: A list of FunctionTool objects
                representing the functions in the toolkit.
        """
        return [
            FunctionTool(self.information_retrieval),
        ]


# add the function to FunctionTool list
RETRIEVAL_FUNCS: List[FunctionTool] = RetrievalToolkit().get_tools()
