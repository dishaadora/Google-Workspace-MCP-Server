# Google Workspace MCP Server

A Model Context Protocol (MCP) server that acts as a secure bridge between your personal Google Workspace account (Gmail, Calendar, etc.) and any MCP-compatible AI client, such as a custom agent built with `mcp-use`.

## Features

*   **Google Calendar**:
    *   Effortlessly list and search for events on your primary calendar within a specific date range.
    *   Create new events with detailed information like title, description, start, and end times.
    *   Update existing events, allowing for partial modifications such as changing the title or time.
    *   Delete events directly from your calendar.
*   **Gmail**:
    *   Read the content of your most recent email to stay up-to-date.
    *   Search for specific emails by their subject line to find important conversations.
    *   Compose and send new emails directly from your account.
*   **Google Drive**:
    *   Search for files and folders using powerful query strings.
    *   Create new Google Docs with a specified title and initial content.
    *   Update the entire content of an existing Google Doc.
    *   Manage your files by moving them to the bin or deleting them permanently.

## Getting Started

Follow these steps to set up the server and run the example AI agent.

### Prerequisites

*   Python 3.9+ and `uv` (or `pip`).
*   A Google Cloud project with the necessary APIs enabled.
*   An LLM API Key (e.g., from OpenAI, Anthropic, etc.) for the client.
*   The `mcp-use` library and its dependencies.

### Step 1: Configure your Google Cloud Project

You need to authorize this application to access your Google data. This is a one-time setup.

1.  **Go to the Google Cloud Console**: [https://console.cloud.google.com/](https://console.cloud.google.com/)
2.  **Create a new project** (or use an existing one).
3.  **Enable APIs**:
    *   Go to "APIs & Services" -> "Library".
    *   Search for and **Enable** the **Gmail API**.
    *   Search for and **Enable** the **Google Calendar API**.
4.  **Create OAuth Credentials**:
    *   Go to "APIs & Services" -> "Credentials".
    *   Click "Create Credentials" -> "OAuth client ID".
    *   If prompted, configure the "OAuth consent screen". Choose **External** and provide a name for the app. You can skip most other fields for personal use. Add your Google account email as a Test User.
    *   For "Application type", select **Desktop app**.
    *   Give it a name (e.g., "GSuite MCP Client").
5.  **Download Credentials**:
    *   After creating the client ID, click the "Download JSON" icon.
    *   Rename the downloaded file to `client_secrets.json` and place it in the **root directory of this project**.

### Step 2: Install Dependencies

Clone this repository and install the required Python packages for both the server and the client.

```bash
git clone <your-repo-url>
cd <your-repo-name>
uv venv # Create a virtual environment
source .venv/bin/activate # On Windows: .venv\Scripts\activate
# Install server and client dependencies
uv install -r requirements.txt
uv install mcp-use langchain-openai python-dotenv
```

### Step 3: Run the One-Time Authorization

Before you can run the server, you need to authorize it with your Google account. Run the `get_credentials.py` script from your terminal:

```bash
python get_credentials.py
```

*   This will open a browser window.
*   Log in with your Google account and grant the requested permissions.
*   After you approve, the script will automatically create a `token.json` file in the project directory. This file stores your authorization tokens so you don't have to log in every time.

### Step 4: Set Up and Run the AI Agent Client

Instead of a pre-built application, we will use `mcp-use` to create a powerful, custom AI agent that can interact with our server.

1. **Create a .env file**
    Create a `.env` file in your project's root directory to store your environment variables.

2.  **Set Your LLM API Key**:
    ```bash
    # .env
    OPENAI_API_KEY="sk-..."
    ```

3.  **Set Your Server Path**:
    ```bash
    # .env
    MCP_SERVER_ABS_PATH="<your server abs path>"
    ```

4.  **Create the Client Script**:
    Create a file named `mcp_client.py` and add the following code. This script defines an agent that uses an OpenAI model to interact with your GSuite MCP server.

    ```python
    # mcp_client.py
    import asyncio
    from dotenv import load_dotenv
    from langchain_openai import ChatOpenAI
    from mcp_use import MCPAgent, MCPClient

    from config import MCP_SERVER_ABS_PATH

    async def main():
       load_dotenv()
       config = {
          "mcpServers": {
             "gsuite": {
                "command": "python",
                "args": [f"{MCP_SERVER_ABS_PATH}"],
             }
          }
       }

       client = MCPClient.from_dict(config)

       llm = ChatOpenAI(model="gpt-4o")

       # Create agent with the client
       agent = MCPAgent(llm=llm, client=client, max_steps=30)

       result = await agent.run(
          """
          Create a Google Calendar Event based on the content of the last mail being sent to my inbox.
          If you cannot create an event, create a sort of "reminder event" in order to remind me to check that email. 
          """,
       )
       print(f"\nResult: {result}")

    if __name__ == "__main__":
       asyncio.run(main())
    ```

4.  **Run the Agent**:
    Now, execute the client script from your terminal.

    ```bash
    python mcp_client.py
    ```

The script will automatically start the MCP server, connect to it, and run the specified task.

## Roadmap & Future Plans

This server is the foundation for a much larger vision. The goal is to provide a comprehensive MCP server for the entire Google Workspace suite. Future additions will include tools for:

*   📝 **Google Docs**: More granular document manipulation, such as appending text or reading specific sections instead of overwriting the whole file.
*   📊 **Google Sheets**: Read data from sheets, append new rows, update cells, and even perform calculations.
*   📨 New functionalities for **Gmail**.
*   📅 New functionalities for **Google Calendar**.
*   🗂️ New functionalities for **Google Drive**.

Contributions are welcome!

## Contributing

If you'd like to contribute, please feel free to fork the repository and submit a pull request. For major changes, please open an issue first to discuss what you would like to change.

## License

This project is licensed under the MIT License. See the `LICENSE` file for details.
