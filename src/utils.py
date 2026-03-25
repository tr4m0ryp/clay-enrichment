from datetime import datetime

from colorama import Fore, Style
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.output_parsers import StrOutputParser


def get_current_date():
    """Returns the current date formatted as YYYY-MM-DD."""
    return datetime.now().strftime("%Y-%m-%d")


def log_status(message):
    """Prints a status message in yellow. Used for progress updates."""
    print(Fore.YELLOW + message + Style.RESET_ALL)


def log_success(message):
    """Prints a success message in green. Used for completed operations."""
    print(Fore.GREEN + message + Style.RESET_ALL)


def log_error(message):
    """Prints an error message in red. Used for failures and exceptions."""
    print(Fore.RED + message + Style.RESET_ALL)


def get_llm_by_provider(llm_provider, model):
    """
    Returns a LangChain LLM instance for the given provider and model.

    Parameters:
        llm_provider: The provider name ("google", "openai", or "anthropic").
        model: The model identifier string.

    Returns:
        A LangChain chat model instance.
    """
    if llm_provider == "openai":
        from langchain_openai import ChatOpenAI
        llm = ChatOpenAI(model=model, temperature=0.1)
    elif llm_provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        llm = ChatAnthropic(model=model, temperature=0.1)
    elif llm_provider == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI
        llm = ChatGoogleGenerativeAI(model=model, temperature=0.1)
    else:
        raise ValueError(f"Unsupported LLM provider: {llm_provider}")
    return llm


def invoke_llm(
    system_prompt,
    user_message,
    model="gemini-1.5-flash",
    llm_provider="google",
    response_format=None
):
    """
    Invokes an LLM with a system prompt and user message.

    Parameters:
        system_prompt: The system-level instruction for the LLM.
        user_message: The user-level input content.
        model: The model identifier (default: gemini-1.5-flash).
        llm_provider: The provider name (default: google).
        response_format: Optional Pydantic model for structured output.

    Returns:
        The LLM response as a string, or a Pydantic model instance if
        response_format is provided.
    """
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_message),
    ]

    llm = get_llm_by_provider(llm_provider, model)

    if response_format:
        llm = llm.with_structured_output(response_format)
    else:
        llm = llm | StrOutputParser()

    output = llm.invoke(messages)
    return output
