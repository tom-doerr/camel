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
from abc import ABC, abstractmethod
from typing import List


class BaseEmbedding(ABC):
    r"""Abstract base class for text embedding functionalities.  """

    @abstractmethod
    def embed(self, text: str) -> List[float]:
        r"""Generates an embedding for the given text.

        Args:
            text (str): The text for which to generate the embedding.

        Returns:
            List[float]: A list of floating-point numbers representing the
                generated embedding.
        """
        pass

    @abstractmethod
    def get_output_dim(self) -> int:
        r"""Returns the output dimension of the embeddings.

        Returns:
            int: The dimensionality of the embedding for the current model.
        """
        pass