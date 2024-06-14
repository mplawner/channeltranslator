import logging
from telethon import TelegramClient, events
from googletrans import Translator
from datetime import datetime
import time
import openai
import requests
import configparser
import argparse
from duckduckgo_search import DDGS

# Configure logging
log_file = f'ct.log'
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(levelname)s - %(message)s', 
                    handlers=[logging.FileHandler(log_file, 'a', 'utf-8'), 
                              logging.StreamHandler()])
logger = logging.getLogger(__name__)

def load_common_phrases(common_phrases_file):
    try:
        with open(common_phrases_file, 'r') as file:
            phrases = file.readlines()
            return [phrase.strip() for phrase in phrases]
    except FileNotFoundError:
        logging.warning(f"'{common_phrases_file}' not found. Using an empty list of common phrases.")
        return []
    except Exception as e:
        logging.error(f"Error reading from '{common_phrases_file}': {e}")
        return []

def filter_common_phrases(text, common_phrases):
    for phrase in common_phrases:
        text = text.replace(phrase, '')
    return text.strip()

def get_openai_providers(config):
    providers = []
    for section in config.sections():
        if section.startswith('OpenAI'):
            try:
                providers.append({
                    'api_base': config[section]['api_base'],
                    'model': config[section]['model'],
                    'key': config[section]['key']
                })
                translators_enabled[section] = config.getboolean('Translators', section, fallback=True)
            except KeyError as e:
                logging.error(f"Missing key {e} in section {section}")
    return providers

def translate_with_openai(text):
    user_message = user_message_template.format(text=text) 
    for provider in openai_providers:
        openai.api_base = provider['api_base']
        openai.api_key = provider['key']
        try:
            response = openai.ChatCompletion.create(
                model=provider['model'],
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": user_message}
                ]
            )
            return response.choices[0].message['content'].strip(), provider['model']
        except Exception as e:
            logging.error(f"Error with OpenAI provider {provider['api_base']}: {e}")
    return "Translation failed."

def translate_with_deepl(text):
    url = "https://api.deepl.com/v2/translate"
    payload = {
        "auth_key": deepl_key,
        "text": text,
        "target_lang": "EN"
    }
    response = requests.post(url, data=payload)
    return response.json()["translations"][0]["text"]

def translate_with_duckduckgo(text, model, proxy_url=None):
    if proxy_url:
        ddgs = DDGS(proxy=proxy_url)
    else:
        ddgs = DDGS()
    full_message = system_message + " " + user_message_template.format(text=text)
    try:
        result = ddgs.chat(keywords=full_message, model=model)
        return result
    except Exception as e:
        logging.error(f"DuckDuckGo translation error: {e}")
    return "Translation failed."

def main():
    @client.on(events.NewMessage(chats=CHANNELS))
    async def new_message_handler(event):
        original_text = event.message.text

        logging.info(f"New message received: {original_text}")

        common_phrases = load_common_phrases(common_phrases_file)
        filtered_text = filter_common_phrases(original_text, common_phrases)

        media = event.message.media
        channel_username = event.chat.username if event.chat and hasattr(event.chat, 'username') else "unknown"
        channel_link = f"@{channel_username}" if channel_username != "unknown" else "Unknown Channel"

        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')    
        logging.info(f"Channel: {channel_link}, Time: {current_time}")

        translations = {"Original": filtered_text if filtered_text else "Media Post"}

        for provider_name in translators_enabled:
            if translators_enabled[provider_name] and filtered_text:
                logging.info(f"Attempting translation with {provider_name}")
                if provider_name.startswith('OpenAI'):
                    try:
                        translation, model = translate_with_openai(filtered_text)
                        if translation != "Translation failed.":
                            translations[model] = translation
                            break  # Exit the loop after the first successful translation
                    except Exception as e:
                        logging.error(f"{provider_name} translation error: {e}")
                elif provider_name == 'Google':
                    try:
                        translations["Google"] = translator.translate(filtered_text, dest='en').text
                    except Exception as e:
                        logging.error(f"Googletrans error: {e}")
                elif provider_name == 'DeepL':
                    try:
                        translations["DeepL"] = translate_with_deepl(filtered_text)
                    except Exception as e:
                        logging.error(f"DeepL translation error: {e}")
                elif provider_name == 'DuckDuckGo':
                    try:
                        model = config.get('DuckDuckGo', 'model', fallback='llama-3-70b')
                        translations["DuckDuckGo"] = translate_with_duckduckgo(filtered_text, model, duckduckgo_proxy)
                    except Exception as e:
                        logging.error(f"DuckDuckGo translation error: {e}")

        message = f"From {channel_link}:\n\n" + "\n\n".join([f"{key}:\n{value}" for key, value in translations.items()])
        logging.info(message)

        if media:
            try:
                await client.send_file(recipient_group_id, file=media, caption=message)
                logging.info("Media and message sent successfully")
            except Exception as e:
                logging.error(f"Failed to send media and message to the target group: {e}")
        else:
            try:
                await client.send_message(recipient_group_id, message)
                logging.info("Message sent successfully")
            except Exception as e:
                logging.error(f"Failed to send message to the target group: {e}")

    with client:
        client.run_until_disconnected()

if __name__ == "__main__":
    # Setup command line argument parsing
    parser = argparse.ArgumentParser(description="Run the Telegram bot with a configurable settings file.")
    parser.add_argument('-c', '--config', type=str, default='config.ini', help='Path to the configuration file.')
    args = parser.parse_args()

    # Load configuration
    config = configparser.ConfigParser()
    config.read(args.config)

    api_id = int(config['Credentials']['api_id'])
    api_hash = config['Credentials']['api_hash']
    deepl_key = config['Credentials']['deepl_key']
    recipient_group_id = int(config['Telegram']['recipient_group_id'])
    common_phrases_file = config.get('Files', 'common_phrases', fallback='common_phrases.txt')

    system_message = config['Messages']['system_message']
    user_message_template = config['Messages']['user_message']

    client = TelegramClient('anon', api_id, api_hash)

    translator = Translator()

    translators_enabled = {
        'DeepL': config.getboolean('Translators', 'DeepL', fallback=True),
        'Google': config.getboolean('Translators', 'Google', fallback=True),
        'DuckDuckGo': config.getboolean('Translators', 'DuckDuckGo', fallback=False)
    }

    duckduckgo_proxy = config.get('DuckDuckGo', 'proxy', fallback=None)
    
    openai_enabled = config.getboolean('Translators', 'OpenAI', fallback=False)
    if openai_enabled:
        openai_providers = get_openai_providers(config)
    else:
        openai_providers = []
    #openai_providers = get_openai_providers(config)

    CHANNELS = config['Channels']['channels'].split(', ')

    while True:
        try:
            main()
        except Exception as e:
            logging.error(f"Error occurred: {e}. Retrying in 60 seconds.")
            time.sleep(60)
