# Google Workspace MCP Server

A Model Context Protocol (MCP) server that acts as a secure bridge between your personal Google Workspace account (Gmail, Calendar, etc.) and any MCP-compatible AI client, like Claude for Desktop.

## The Concept: Your Personal AI Assistant

Large Language Models are incredibly powerful, but they are limited by the information they were trained on. They don't know about your schedule, your emails, or your personal data.

This MCP server solves that problem. It securely connects to your Google account and exposes specific functionalities (like "read the last email" or "create a calendar event") as **tools** that an AI can use.

Imagine asking your AI assistant:

> "Read my last email and create a calendar event based on its content."

With this server running, the AI can:
1.  Call the `read_latest_gmail_email` tool to get the content of your email.
2.  Understand the context and details for an event.
3.  Call the `create_calendar_event` tool to add it directly to your Google Calendar.

All of this happens through a secure, permission-based flow, giving you a powerful, personalized AI assistant that can automate your daily tasks.

## Features

Currently, this server supports the following tools:

*   **Gmail**:
    *   `read_latest_gmail_email`: Fetches the snippet and body of the most recent email in your inbox.
*   **Google Calendar**:
    *   `create_calendar_event`: Creates a new event in your primary calendar.

## Getting Started

Follow these steps to set up and run the server.

### Prerequisites

*   Python 3.9+ and `uv` (or `pip`).
*   An MCP Client, such as [Claude for Desktop](https://claude.ai/download).
*   A Google Cloud project with the necessary APIs enabled.

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

Clone this repository and install the required Python packages.

```bash
git clone <your-repo-url>
cd <your-repo-name>
uv venv # Create a virtual environment
source .venv/bin/activate # On Windows: .venv\Scripts\activate
uv install -r requirements.txt
```

### Step 3: Run the One-Time Authorization

Before you can run the server, you need to authorize it with your Google account. Run the `get_credentials.py` script from your terminal:

```bash
python get_credentials.py
```

*   This will open a browser window.
*   Log in with your Google account and grant the requested permissions.
*   After you approve, the script will automatically create a `token.json` file in the project directory. This file stores your authorization tokens so you don't have to log in every time.

### Step 4: Configure your MCP Client (e.g., Claude Desktop)

Now, tell your MCP client how to run the server. Open the Claude for Desktop configuration file:

*   **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
*   **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

Add the following configuration, making sure to replace the placeholder with the **absolute path** to your project directory.

```json
{
  "mcpServers": {
    "gsuite_mcp_server": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/path/to/your/project/GsuiteMCPServer",
        "python",
        "mcp_server.py"
      ]
    }
  }
}
```

*Replace `/path/to/your/project/GsuiteMCPServer` with the actual absolute path on your system.*

### Step 5: Restart and Use

Restart Claude for Desktop completely. You should now see the tool indicator appear. You can start giving it commands that use your Gmail and Calendar!

**Example Prompts:**

*   "Can you check my last email and summarize it for me?"
*   "Read my latest email. It's an invitation for a meeting. Please create a calendar event for it tomorrow at 3 PM, titled 'Project Kick-off'."

## Roadmap & Future Plans

This server is the foundation for a much larger vision. The goal is to provide a comprehensive MCP server for the entire Google Workspace suite. Future additions will include tools for:

*   ✅ **Gmail** (reading)
*   ✅ **Google Calendar** (creating events)
*   📝 **Google Docs**: Create, read, and append to documents.
*   📊 **Google Sheets**: Read data from sheets, append new rows, and even perform calculations.
*   🗂️ **Google Drive**: List files, download content, and upload new files.

Contributions are welcome!

## Contributing

If you'd like to contribute, please feel free to fork the repository and submit a pull request. For major changes, please open an issue first to discuss what you would like to change.

## License

This project is licensed under the MIT License. See the `LICENSE` file for details.