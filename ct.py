import argparse
import asyncio
import configparser
import hashlib
import logging
import os
import re
import sys
from datetime import datetime, timedelta

import aiohttp
import openai
from duckduckgo_search import DDGS
from googletrans import Translator
from telethon import TelegramClient, events
from telethon.errors.rpcerrorlist import UsernameInvalidError

# Constants
LOG_FILE = 'ct.log'
PROCESSED_MESSAGE_RETENTION_MINUTES = 30
CAPTION_MAX_LENGTH = 1024


def setup_logging(log_file=LOG_FILE):
    """Configure logging for the script."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    return logging.getLogger(__name__)


def load_common_phrases(common_phrases_file, logger):
    """Load common phrases from a file."""
    try:
        with open(common_phrases_file, 'r', encoding='utf-8') as file:
            phrases = [line.strip() for line in file if line.strip()]
            return phrases
    except FileNotFoundError:
        logger.warning(f"'{common_phrases_file}' not found. Using an empty list of common phrases.")
        return []
    except Exception as e:
        logger.error(f"Error reading from '{common_phrases_file}': {e}")
        return []


def filter_common_phrases(text, common_phrases):
    """Remove common phrases from the text."""
    for phrase in common_phrases:
        text = text.replace(phrase, '')
    return text.strip()


def get_openai_providers(config, translators_enabled, logger):
    """Retrieve OpenAI provider configurations from the config."""
    providers = []
    for section in config.sections():
        if section.startswith('OpenAI'):
            try:
                api_base = config[section]['api_base']
                model = config[section]['model']
                key = config[section]['key']
                enabled = config.getboolean('Translators', section, fallback=True)
                if enabled:
                    providers.append({'api_base': api_base, 'model': model, 'key': key})
                translators_enabled[section] = enabled
            except KeyError as e:
                logger.error(f"Missing key {e} in section {section}")
    return providers


async def translate_with_openai(text, openai_providers, system_message, user_message_template, logger):
    """Translate text using OpenAI providers asynchronously."""
    user_message = user_message_template.format(text=text)
    for provider in openai_providers:
        openai.api_base = provider['api_base']
        openai.api_key = provider['key']
        try:
            response = await openai.ChatCompletion.acreate(
                model=provider['model'],
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": user_message}
                ]
            )
            translation = response.choices[0].message['content'].strip()
            return translation, provider['model']
        except Exception as e:
            logger.error(f"Error with OpenAI provider {provider['api_base']}: {e}")
            logger.exception(e)
    return "Translation failed.", None


async def translate_with_deepl(text, deepl_key, logger):
    """Translate text using DeepL asynchronously."""
    if not deepl_key:
        logger.error("DeepL API key is not set.")
        return "Translation failed."
    url = "https://api.deepl.com/v2/translate"
    params = {
        "auth_key": deepl_key,
        "text": text,
        "target_lang": "EN"
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=params) as response:
                response.raise_for_status()
                data = await response.json()
                return data["translations"][0]["text"]
    except Exception as e:
        logger.error(f"DeepL API error: {e}")
        logger.exception(e)
        return "Translation failed."


async def translate_with_duckduckgo(text, model, proxy_url, system_message, user_message_template, logger):
    """Translate text using DuckDuckGo, offloading to a thread."""
    def duckduckgo_translate():
        ddgs = DDGS(proxy=proxy_url) if proxy_url else DDGS()
        full_message = system_message + " " + user_message_template.format(text=text)
        try:
            result = ddgs.chat(keywords=full_message, model=model)
            return result
        except Exception as e:
            logger.error(f"DuckDuckGo translation error: {e}")
            logger.exception(e)
            return "Translation failed."
    translation = await asyncio.to_thread(duckduckgo_translate)
    return translation


async def translate_with_google(text, translator, logger):
    """Translate text using Google Translate asynchronously."""
    def google_translate():
        try:
            result = translator.translate(text, dest='en')
            return result.text
        except Exception as e:
            logger.error(f"Googletrans error: {e}")
            logger.exception(e)
            return "Translation failed."
    translation = await asyncio.to_thread(google_translate)
    return translation


async def hash_message(message):
    """Create a hash of the message asynchronously."""
    def compute_hexdigest(msg):
        return hashlib.md5(msg.encode('utf-8')).hexdigest()
    return await asyncio.to_thread(compute_hexdigest, message)


def cleanup_processed_messages(processed_messages, retention_minutes=PROCESSED_MESSAGE_RETENTION_MINUTES):
    """Remove old messages from the processed messages dictionary."""
    current_time = datetime.now()
    cutoff_time = current_time - timedelta(minutes=retention_minutes)
    keys_to_remove = [k for k, v in processed_messages.items() if v < cutoff_time]
    for key in keys_to_remove:
        del processed_messages[key]


def truncate_caption(caption, max_length=CAPTION_MAX_LENGTH):
    """Truncate caption to the maximum allowed length."""
    return caption if len(caption) <= max_length else caption[:max_length - 3] + "..."


async def resolve_channels(client, channels, logger):
    """Resolve channel usernames to entities."""
    resolved_channels = []
    for channel in channels:
        try:
            entity = await client.get_input_entity(channel)
            resolved_channels.append(entity)
            logger.info(f"Successfully resolved channel: {channel}")
        except UsernameInvalidError:
            logger.error(f"Invalid username: '{channel}'")
        except Exception as e:
            logger.error(f"Error resolving channel '{channel}': {e}")
    return resolved_channels


async def main():
    """Main function to run the Telegram client."""
    # Setup logging
    logger = setup_logging()
    processed_messages = {}

    # Setup command-line argument parsing
    parser = argparse.ArgumentParser(description="Run the Telegram bot with a configurable settings file.")
    parser.add_argument('-c', '--config', type=str, default='config.ini', help='Path to the configuration file.')
    args = parser.parse_args()

    # Load configuration
    config = configparser.ConfigParser()
    config.read(args.config)

    # Validate and load essential configurations
    try:
        api_id = int(config['Credentials']['api_id'])
        api_hash = config['Credentials']['api_hash']
        recipient_group_id = int(config['Telegram']['recipient_group_id'])
        system_message = config['Messages']['system_message']
        user_message_template = config['Messages']['user_message']
    except KeyError as e:
        logger.error(f"Missing configuration for {e}. Please check your config file.")
        sys.exit(1)

    common_phrases_file = config.get('Files', 'common_phrases', fallback='common_phrases.txt')
    deepl_key = config['Credentials'].get('deepl_key', '')
    duckduckgo_proxy = config.get('DuckDuckGo', 'proxy', fallback=None)
    ddg_model = config.get('DuckDuckGo', 'model', fallback='llama-3-70b')

    # Initialize translators_enabled dictionary
    translators_enabled = {
        'DeepL': config.getboolean('Translators', 'DeepL', fallback=True),
        'Google': config.getboolean('Translators', 'Google', fallback=True),
        'DuckDuckGo': config.getboolean('Translators', 'DuckDuckGo', fallback=False)
    }

    # Load OpenAI providers
    openai_enabled = config.getboolean('Translators', 'OpenAI', fallback=False)
    if openai_enabled:
        openai_providers = get_openai_providers(config, translators_enabled, logger)
    else:
        openai_providers = []

    # Validate and process CHANNELS
    channels_config = config.get('Channels', 'channels', fallback='').strip()
    if not channels_config:
        logger.error("No channels specified in the 'Channels' section of the configuration file.")
        sys.exit(1)

    CHANNELS = [channel.strip().lstrip('@') for channel in channels_config.split(',') if channel.strip()]
    if not CHANNELS:
        logger.error("No valid channels found after processing the 'channels' configuration.")
        sys.exit(1)

    # Validate usernames
    USERNAME_REGEX = re.compile(r'^[a-zA-Z][\w\d]{4,31}$')
    invalid_usernames = [channel for channel in CHANNELS if not USERNAME_REGEX.match(channel)]
    if invalid_usernames:
        logger.error(f"Invalid usernames detected: {invalid_usernames}")
        sys.exit(1)

    logger.info(f"Listening to channels: {CHANNELS}")

    # Load common phrases
    common_phrases = load_common_phrases(common_phrases_file, logger)

    # Initialize Telegram client
    client = TelegramClient('anon', api_id, api_hash)

    # Start the client before resolving channels
    try:
        await client.start()
    except Exception as e:
        logger.exception("Failed to start the Telegram client.")
        sys.exit(1)

    # Resolve channels
    channel_entities = await resolve_channels(client, CHANNELS, logger)
    if not channel_entities:
        logger.error("No valid channels to listen to after resolving entities.")
        sys.exit(1)

    # Initialize the translator
    translator = Translator()

    @client.on(events.NewMessage(chats=channel_entities))
    async def new_message_handler(event):
        start_time = datetime.now()
        original_text = event.message.text or ''
        if not original_text.strip():
            logger.info("Received a message with no text. Skipping.")
            return

        # Asynchronously clean up processed messages
        cleanup_processed_messages(processed_messages)

        # Asynchronously hash the message
        message_hash = await hash_message(original_text)
        if message_hash in processed_messages:
            logger.info("Duplicate message detected. Ignoring.")
            return
        processed_messages[message_hash] = datetime.now()

        logger.info(f"New message received: {original_text}")

        filtered_text = filter_common_phrases(original_text, common_phrases)
        media = event.message.media
        channel_username = getattr(event.chat, 'username', 'unknown')
        channel_link = f"@{channel_username}" if channel_username != 'unknown' else "Unknown Channel"

        translations = {"Original": filtered_text if filtered_text else "Media Post"}

        # Attempt translations asynchronously
        for provider_name, enabled in translators_enabled.items():
            if enabled and filtered_text:
                logger.info(f"Attempting translation with {provider_name}")
                try:
                    if provider_name.startswith('OpenAI'):
                        translation, model = await translate_with_openai(
                            filtered_text, openai_providers, system_message, user_message_template, logger
                        )
                        if translation != "Translation failed.":
                            translations[model] = translation
                            break  # Exit after first successful translation
                    elif provider_name == 'Google':
                        translation = await translate_with_google(filtered_text, translator, logger)
                        translations["Google"] = translation
                    elif provider_name == 'DeepL':
                        translation = await translate_with_deepl(filtered_text, deepl_key, logger)
                        translations["DeepL"] = translation
                    elif provider_name == 'DuckDuckGo':
                        translation = await translate_with_duckduckgo(
                            filtered_text, ddg_model, duckduckgo_proxy, system_message, user_message_template, logger
                        )
                        translations["DuckDuckGo"] = translation
                except Exception as e:
                    logger.error(f"{provider_name} translation error: {e}")
                    logger.exception(e)

        message_content = f"From {channel_link}:\n\n" + "\n\n".join(
            [f"{key}:\n{value}" for key, value in translations.items()]
        )
        logger.info(f"Final message to send: {message_content}")
        caption = truncate_caption(message_content)

        try:
            if media:
                await client.send_file(recipient_group_id, file=media, caption=caption)
                logger.info("Media and message sent successfully.")
            else:
                await client.send_message(recipient_group_id, message_content)
                logger.info("Message sent successfully.")
        except Exception as e:
            logger.error(f"Failed to send message to the target group: {e}")
            logger.exception(e)

        end_time = datetime.now()
        processing_time = (end_time - start_time).total_seconds()
        logger.info(f"Message processed in {processing_time:.2f} seconds")

    # Run the client
    try:
        await client.run_until_disconnected()
    except KeyboardInterrupt:
        logger.info("Script terminated by user.")
    except Exception as e:
        logger.exception("An error occurred while running the client.")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

