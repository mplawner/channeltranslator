# Channel Translator

This repository contains a script that monitors Telegram channels for updated events, translates those events, and sends them to a Telegram group. Multiple translation options available.

## Features

- **Telegram Client**: Uses the Telethon library to interact with Telegram.
- **Translation**: Integrates with multiple translation APIs.
- **OpenAI Integration**: Connects with OpenAI's API to leverage its capabilities.
- **Web Search**: Uses DuckDuckGo search to fetch information from the web.
- **Logging**: Logs activities and errors to a file and the console.
- **Common Phrases**: Supports loading and using common phrases from a file.

## Installation

1. **Clone the repository**:
   ```bash
   git clone https://github.com/yourusername/telegram-translation-info-bot.git
   cd telegram-translation-info-bot
   ```

2. **Install the dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure the bot**:
   - Create a `config.ini` file in the root directory with your API keys and settings. Refer to the detailed configuration instructions below.

## Configuration Options

The `config.ini` file supports the following sections and options:

### [Credentials]

- `api_id`: Your Telegram API ID (required).
- `api_hash`: Your Telegram API hash (required).
- `deepl_key`: Your DeepL API key (required if using DeepL).

### [OpenAI#]

You can add multiple OpenAI providers by creating sections with names like `[OpenAI1]`, `[OpenAI2]`, etc. At least one is required if `Translators / OpenAI` is true. The first successful connection will be used per each event.

- `api_base`: The base URL for the OpenAI API (required, default: `https://api.openai.com/v1`).
- `model`: The model to use for OpenAI (required, default: `gpt-3.5-turbo`).
- `key`: Your OpenAI API key (required).

### [Files]

- `common_phrases`: The file containing common phrases to be removed from translation, like ads or signatures (optional, default: `common_phrases.txt`).

### [Translators]

- `OpenAI`: Whether to use OpenAI for translation (required, `true` or `false`).
- `DeepL`: Whether to use DeepL for translation (required, `true` or `false`).
- `Google`: Whether to use Google Translate for translation (required, `true` or `false`).
- `DuckDuckGo`: Whether to use DuckDuckGo for translation (required, `true` or `false`).

### [DuckDuckGo]

- `model`: The model to use for DuckDuckGo translations (optional, default: `llama-3-70b`).
- `proxy`: Proxy setting for the DuckDuckGo Search function (optional, default: None).

### [Channels]

- `channels`: A list of channels to monitor, e.g., `@channel1, @channel2` (at least one required).

### [Telegram]

- `recipient_group_id`: The recipient group ID for Telegram messages (required).

### [Messages]

- `system_message`: The system message for the AI model (required, see example below).
- `user_message`: The user message template for translation requests. Will replace '{text}' with text of message. (required, see example below).

Example `config.ini`:

```ini
[Credentials]
api_id = *** REDACTED ***
api_hash = *** REDACTED ***
deepl_key = *** REDACTED ***

[OpenAI1]
api_base = https://api.openai.com/v1
model = gpt-3.5-turbo
key = *** REDACTED ***

[Files]
common_phrases = common_phrases.txt

[Translators]
OpenAI = true 
DeepL = false
Google = false
DuckDuckGo = true

[DuckDuckGo]
model = llama-3-70b
proxy = 

[Channels]
channels = @channel1, @channel2

[Telegram]
recipient_group_id = *** REDACTED ***

[Messages]
system_message = "You are an AI language model tasked with translating text from various sources into English. Ensure that the translation is accurate, maintains the original meaning, and is written in clear and natural English. If any part of the text is unclear or ambiguous, provide the best possible translation based on context."
user_message = Translate '{text}' to English. Only provide the translation, no additional information.
```

## How it Works

- The bot iterates through each `[OpenAI#]` section for translation attempts and stops after a successful translation.
- If multiple translators are enabled in the `[Translators]` section, the script will attempt to use each one in the order listed and stop after a successful translation.

## Usage

Run the bot using the following command:

```bash
python ct.py --config config.ini
```

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

## Contributing

Contributions are welcome! Please open an issue or submit a pull request for any improvements or bug fixes.

## Acknowledgements

- [Telethon](https://github.com/LonamiWebs/Telethon)
- [Google Translate API](https://cloud.google.com/translate)
- [OpenAI](https://www.openai.com/)
- [DuckDuckGo Search API](https://github.com/deedy5/duckduckgo_search)
