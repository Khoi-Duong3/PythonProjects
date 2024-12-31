import discord
import os
import asyncio
from dotenv import load_dotenv
import yt_dlp

def run_bot():
    load_dotenv()
    TOKEN = os.getenv("discord_token")
    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)

    voice_clients = {}
    yt_dl_options = {"format": "bestaudio/best"}
    ytdl = yt_dlp.YoutubeDL(yt_dl_options)

    ffmpeg_options = {'options': '-vn', "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"}

    @client.event
    async def on_ready():
        print(f"{client.user} is now jamming")

    @client.event
    async def on_message(message):
        if message.content.startswith("?play"):
            try:
                voice_client = await message.author.voice.channel.connect()
                voice_clients[voice_client.guild.id] = voice_client
            except Exception as e:
                print(e)

            try:
                url = message.content.split()[1]

                loop = asyncio.get_event_loop()
                data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=False))

                song = data["url"]
                player = discord.FFmpegPCMAudio(song, **ffmpeg_options)

                voice_clients[message.guild.id].play(player)
            
            except Exception as e:
                print(e)

        if message.content.startswith("?pause"):
            try:
                voice_clients[message.guild.id].pause()
            except Exception as e:
                print(e)
        
        if message.content.startswith("?resume"):
            try:
                voice_clients[message.guild.id].resume()
            except Exception as e:
                print(e)
        
        if message.content.startswith("?stop"):
            try:
                voice_clients[message.guild.id].stop()
                await voice_clients[message.guild.id].disconnect()
            except Exception as e:
                print(e)

    client.run(TOKEN)