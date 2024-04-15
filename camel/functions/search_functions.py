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
import os
from typing import Any, Callable, Dict, List

from camel.agents import ChatAgent
from camel.functions import OpenAIFunction
from camel.messages import BaseMessage
from camel.prompts import TextPrompt


def search_wiki(entity: str) -> str:
    r"""Search the entity in WikiPedia and return the summary of the required
        page, containing factual information about the given entity.

    Args:
        entity (str): The entity to be searched.

    Returns:
        str: The search result. If the page corresponding to the entity
            exists, return the summary of this entity in a string.
    """
    try:
        import wikipedia
    except ImportError:
        raise ImportError(
            "Please install `wikipedia` first. You can install it by running "
            "`pip install wikipedia`.")

    result: str

    try:
        result = wikipedia.summary(entity, sentences=5, auto_suggest=False)
    except wikipedia.exceptions.DisambiguationError as e:
        result = wikipedia.summary(e.options[0], sentences=5,
                                   auto_suggest=False)
    except wikipedia.exceptions.PageError:
        result = ("There is no page in Wikipedia corresponding to entity "
                  f"{entity}, please specify another word to describe the"
                  " entity to be searched.")
    except wikipedia.exceptions.WikipediaException as e:
        result = f"An exception occurred during the search: {e}"

    return result


def search_duckduckgo(query: str,
                      max_results: int = 10) -> List[Dict[str, Any]]:
    r"""Use DuckDuckGo search engine to search information for the given query.

    This function queries the DuckDuckGo API for related topics to the given
    search term. The results are formatted into a list of dictionaries, each
    representing a search result.

    Args:
        query (str): The query to be searched.

    Returns:
        List[Dict[str, Any]]: A list of dictionaries where each dictionary
        represents a search result.
            Each dictionary contains the following keys:
            - 'result_id': A sequential number starting from 1.
            - 'title': The title or main text of the search result.
            - 'description': A brief description of the result, often similar
                to the title.
            - 'long_description': More detail of the result, often the same as
                the description.
            - 'url': The URL of the result.

            Example:
            {
                'result_id': 1,
                'title': 'DuckDuckGo',
                'description': 'DuckDuckGo is an Internet search engine ' + \
                    'that emphasizes protecting searchers' privacy.',
                'long_description': 'DuckDuckGo is an Internet search ' + \
                    'engine that emphasizes protecting searchers' privacy.',
                'url': 'https://www.duckduckgo.com'
            }
        title, description, url of a search result.
    """
    from duckduckgo_search import DDGS
    from requests.exceptions import RequestException

    ddgs = DDGS()
    responses = []

    try:
        results = [
            r for r in ddgs.text(keywords=query, max_results=max_results)
        ]

        # Iterate over results found
        for i, result in enumerate(results, start=1):
            # Extracting data from each result
            title = result["title"]
            body = result["body"]
            url = result["href"]

            # Creating a response object with a similar structure
            response = {
                "result_id": i,
                "title": title,
                "description": body,
                "url": url
            }
            responses.append(response)

    except RequestException as e:
        # Handle specific exceptions or general request exceptions
        responses.append({"error": f"DuckDuckGo search failed: {str(e)}"})
    except Exception as e:
        # Catch-all for any other exceptions that were not anticipated
        responses.append({"error": f"An unexpected error occurred: {str(e)}"})

    return responses


def search_google(query: str,
                  num_result_pages: int = 10) -> List[Dict[str, Any]]:
    r"""Use Google search engine to search information for the given query.

    Args:
        query (str): The query to be searched.

    Returns:
        List[Dict[str, Any]]: A list of dictionaries where each dictionary
        represents a website.
            Each dictionary contains the following keys:
            - 'result_id': A number in order.
            - 'title': The title of the website.
            - 'description': A brief description of the website.
            - 'long_description': More detail of the website.
            - 'url': The URL of the website.

            Example:
            {
                'result_id': 1,
                'title': 'OpenAI',
                'description': 'An organization focused on ensuring that
                artificial general intelligence benefits all of humanity.',
                'long_description': 'OpenAI is a non-profit artificial
                intelligence research company. Our goal is to advance digital
                intelligence in the way that is most likely to benefit humanity
                as a whole',
                'url': 'https://www.openai.com'
            }
        title, description, url of a website.
    """
    import requests

    # https://developers.google.com/custom-search/v1/overview
    GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
    # https://cse.google.com/cse/all
    SEARCH_ENGINE_ID = os.getenv("SEARCH_ENGINE_ID")

    # Using the first page
    start_page_idx = 1
    # Different language may get different result
    search_language = "en"
    # How many pages to return
    num_result_pages = 10
    # Constructing the URL
    # Doc: https://developers.google.com/custom-search/v1/using_rest
    url = f"https://www.googleapis.com/customsearch/v1?" \
          f"key={GOOGLE_API_KEY}&cx={SEARCH_ENGINE_ID}&q={query}&start=" \
          f"{start_page_idx}&lr={search_language}&num={num_result_pages}"

    responses = []
    # Fetch the results given the URL
    try:
        # Make the get
        result = requests.get(url)
        data = result.json()

        # Get the result items
        if "items" in data:
            search_items = data.get("items")

            # Iterate over 10 results found
            for i, search_item in enumerate(search_items, start=1):
                if "og:description" in search_item["pagemap"]["metatags"][0]:
                    long_description = \
                        search_item["pagemap"]["metatags"][0]["og:description"]
                else:
                    long_description = "N/A"
                # Get the page title
                title = search_item.get("title")
                # Page snippet
                snippet = search_item.get("snippet")

                # Extract the page url
                link = search_item.get("link")
                response = {
                    "result_id": i,
                    "title": title,
                    "description": snippet,
                    "long_description": long_description,
                    "url": link
                }
                responses.append(response)
        else:
            responses.append({"error": "google search failed."})

    except requests.RequestException:
        responses.append({"error": "google search failed."})

    return responses


def text_extract_from_web(url: str) -> str:
    r"""Get the text information from given url.

    Args:
        url (str): The website you want to search.

    Returns:
        str: All texts extract from the web.
    """
    import requests
    from newspaper import Article

    try:
        # Request the target page
        article = Article(url)
        article.download()
        article.parse()
        text = article.text.replace("\n", "")

    except requests.RequestException:
        text = f"can't access {url}"

    return text


# Split a text into smaller chunks of size n
def create_chunks(text: str, n: int) -> List[str]:
    r"""Returns successive n-sized chunks from provided text."

    Args:
        text (str): The text to be split.
        n (int): The max length of a single chunk.

    Returns:
        List[str]: A list of split texts.
    """

    chunks = []
    i = 0
    while i < len(text):
        # Find the nearest end of sentence within a range of 0.5 * n
        # and 1.5 * n tokens
        j = min(i + int(1.2 * n), len(text))
        while j > i + int(0.8 * n):
            # Decode the tokens and check for full stop or newline
            chunk = text[i:j]
            if chunk.endswith(".") or chunk.endswith("\n"):
                break
            j -= 1
        # If no end of sentence found, use n tokens as the chunk size
        if j == i + int(0.8 * n):
            j = min(i + n, len(text))
        chunks.append(text[i:j])
        i = j
    return chunks


def prompt_single_step_agent(prompt: str) -> str:
    """Prompt a single-step agent to summarize texts or answer a question."""

    assistant_sys_msg = BaseMessage.make_assistant_message(
        role_name="Assistant",
        content="You are a helpful assistant.",
    )
    agent = ChatAgent(assistant_sys_msg)
    agent.reset()

    user_msg = BaseMessage.make_user_message(
        role_name="User",
        content=prompt,
    )
    assistant_response = agent.step(user_msg)
    if assistant_response.msgs is not None:
        return assistant_response.msg.content
    return ""


def summarize_text(text: str, query: str) -> str:
    r"""Summarize the information from the text, base on the query if query is
        given.

    Args:
        text (str): Text to summarize.
        query (str): What information you want.

    Returns:
        str: Strings with information.
    """
    summary_prompt = TextPrompt(
        '''Gather information from this text that relative to the question, but
         do not directly answer the question.\nquestion: {query}\ntext ''')
    summary_prompt = summary_prompt.format(query=query)
    # Max length of each chunk
    max_len = 3000
    results = ""
    chunks = create_chunks(text, max_len)
    # Summarize
    for i, chunk in enumerate(chunks, start=1):
        prompt = summary_prompt + str(i) + ": " + chunk
        result = prompt_single_step_agent(prompt)
        results += result + "\n"

    # Final summarise
    final_prompt = TextPrompt(
        '''Here are some summarized texts which split from one text, Using the
        information to answer the question: {query}.\n\nText: ''')
    final_prompt = final_prompt.format(query=query)
    prompt = final_prompt + results

    response = prompt_single_step_agent(prompt)

    return response


def continue_search(query: str, answer: str) -> bool:
    r"""Ask LLM whether to continue search or not.

    Args:
        query (str): Question you want to be answered.
        answer (str): Answer to the query.

    Returns:
        bool: True if the user want to continue search, False otherwise.
    """
    prompt = TextPrompt("Do you think the ANSWER can answer the QUERY? "
                        "Use only 'yes' or 'no' to answer\n"
                        "===== QUERY ====={query}\n\n"
                        "===== ANSWER ====={answer}")
    prompt = prompt.format(query=query, answer=answer)
    reply = prompt_single_step_agent(prompt)
    if "yes" in str(reply).lower():
        return False
    return True


def search_and_summarize(query: str, search_func: Callable) -> str:
    """
    Search the web for information using a specified search function
    and summarize the results.

    Args:
        query (str): Question you want to be answered.
        search_func (Callable): A function that takes a query.
        and returns search results.

    Returns:
        str: Summarized information from the web.
    """
    responses = search_func(query)
    for item in responses:
        if "url" in item:
            url = item.get("url")
            try:
                extracted_text = text_extract_from_web(str(url))
            except Exception:
                continue
            answer = summarize_text(extracted_text, query)
            if not continue_search(query=query, answer=answer):
                return answer
    return "Failed to find an answer."


def choose_search_and_summarize(query: str) -> str:
    """
    Choose between Google and DuckDuckGo search based on the availability
    of Google API credentials, and summarize the results.

    Args:
        query (str): Question you want to be answered.

    Returns:
        str: Summarized information from the web.
    """
    if os.getenv("GOOGLE_API_KEY") and os.getenv("SEARCH_ENGINE_ID"):
        return search_and_summarize(query, search_google)
    else:
        return search_and_summarize(query, search_duckduckgo)


def search_wolfram_alpha(query: str, is_detailed: bool) -> str:
    r"""Queries Wolfram|Alpha and returns the result. Wolfram|Alpha is a
    search engine that uses algorithms, knowledgebase and AI to compute
    expert-level answers for math, science, society, everyday life and more.

    Args:
        query (str): The query to send to Wolfram Alpha.
        is_detailed (bool): Whether to include additional details in the
            result.

    Returns:
        str: The result from Wolfram Alpha, formatted as a string.
    """
    try:
        import wolframalpha
    except ImportError:
        raise ImportError(
            "Please install `wolframalpha` first. You can install it by "
            "running `pip install wolframalpha`.")

    WOLFRAMALPHA_APP_ID = os.environ.get('WOLFRAMALPHA_APP_ID')
    if not WOLFRAMALPHA_APP_ID:
        raise ValueError("`WOLFRAMALPHA_APP_ID` not found in environment "
                         "variables. Get `WOLFRAMALPHA_APP_ID` here: "
                         "`https://products.wolframalpha.com/api/`.")

    try:
        client = wolframalpha.Client(WOLFRAMALPHA_APP_ID)
        res = client.query(query)
        assumption = next(res.pods).text or "No assumption made."
        answer = next(res.results).text or "No answer found."
    except Exception as e:
        if isinstance(e, StopIteration):
            return "Wolfram Alpha wasn't able to answer it"
        else:
            error_message = (f"Wolfram Alpha wasn't able to answer it"
                             f"{str(e)}.")
            return error_message

    result = f"Assumption:\n{assumption}\n\nAnswer:\n{answer}"

    # Add additional details in the result
    if is_detailed:
        result += '\n'
        for pod in res.pods:
            result += '\n' + pod['@title'] + ':\n'
            for sub in pod.subpods:
                result += (sub.plaintext or "None") + '\n'

    return result.rstrip()  # Remove trailing whitespace


SEARCH_FUNCS: List[OpenAIFunction] = [
    OpenAIFunction(func)  # type: ignore
    for func in
    [search_wiki, choose_search_and_summarize, search_wolfram_alpha]
]
