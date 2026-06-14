import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession

async def main():
    api_id = int(input("API ID: "))
    api_hash = input("API Hash: ")
    phone = input("Phone (+380...): ")

    client = TelegramClient(StringSession(), api_id, api_hash)
    await client.connect()

    sent = await client.send_code_request(phone)
    print("Code request sent.")
    print("Phone code hash:", sent.phone_code_hash)
    print("Now check Telegram chat 777000 / Telegram service notifications.")

    code = input("Code: ")
    await client.sign_in(phone=phone, code=code, phone_code_hash=sent.phone_code_hash)

    print("\nSESSION STRING:\n")
    print(client.session.save())

    await client.disconnect()

asyncio.run(main())