import os

from dotenv import load_dotenv
from openai import OpenAI


load_dotenv()


def main():

    api_key = os.getenv(
        "OPENAI_API_KEY",
        ""
    ).strip()

    model = os.getenv(
        "ASTRA_MODEL",
        "gpt-6-astra"
    ).strip()

    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is missing."
        )

    client = OpenAI(
        api_key=api_key
    )

    print()
    print("GPT-6 ASTRA CONNECTION TEST")
    print("---------------------------")
    print(f"Model: {model}")

    response = client.responses.create(
        model=model,

        input=(
            "Reply with exactly: "
            "ASTRA_CONNECTION_OK"
        ),

        reasoning={
            "effort": "low"
        },

        max_output_tokens=100,
        store=False,
    )

    print(
        f"Response: "
        f"{response.output_text.strip()}"
    )


if __name__ == "__main__":
    main()