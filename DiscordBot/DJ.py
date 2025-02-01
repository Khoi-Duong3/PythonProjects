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

    music_queues = {}

    currently_playing = {}

    yt_dl_options = {"format": "bestaudio/best"}
    ytdl = yt_dlp.YoutubeDL(yt_dl_options)

    ffmpeg_options = {'options': '-vn', "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"}

    @client.event
    async def on_ready():
        print(f"{client.user} is now jamming")

    async def play_next_song(guild_id):
        voice_client = voice_clients.get(guild_id)
        if not voice_client or not voice_client.is_connected():
            return
        queue = music_queues.get(guild_id)
        if not queue:
            return
        
        if queue.empty():
            return

        song_info = await queue.get()

        currently_playing[guild_id] = song_info

        player = discord.FFmpegPCMAudio(song_info["url"], **ffmpeg_options)

        def after_playing(error):
            if (error):
                print (f"Error in playback: {error}")
            coro = play_next_song(guild_id)
            fut = asyncio.run_coroutine_threadsafe(coro, client.loop)
            try:
                fut.result()
            except Exception as e:
                print(e)
        
        voice_client.play(player, after=after_playing)

    async def helper(guild_id, new_songs):
        if guild_id not in music_queues:
            music_queues[guild_id] = asyncio.Queue()
        
        old_queue = []

        while not music_queues[guild_id].empty():
            old_queue.append(await music_queues[guild_id].get())
        
        for song in new_songs:
            await music_queues[guild_id].put(song)
        
        for song in old_queue:
            await music_queues[guild_id].put(song)


    @client.event
    async def on_message(message):
        if message.author == client.user:
            return

        if message.content.startswith("?play"):
            try:
                if not message.author.voice or not message.author.voice.channel:
                    await message.channel.send("You must be in a voice channel to play music")
                    return
                
                command_text = message.content[len("?play"):].strip()
                if not command_text:
                    await message.channel.send("Please provide a song name and artist `?play`.")
                    return

                if " by " in command_text.lower():
                    song_name, artist_name = command_text.split(" by ", 1)
                    song_name = song_name.strip()
                    artist_name = artist_name.strip()
                    search_query = f"ytsearch:{command_text} by {artist_name} lyrics"
                else:
                    search_query = f"ytsearch:{command_text}"
                
                processing_message = await message.channel.send(f"Searching for {command_text} on YouTube...")
                loop = asyncio.get_running_loop()
                data = await loop.run_in_executor(
                    None,
                    lambda: ytdl.extract_info(search_query, download=False)
                )
                lyric_result = None
                if "entries" in data and len(data["entries"]) > 0:
                    for result in data["entries"]:
                        title = result.get("title", "").lower()
                        if "lyric" in title:
                            lyric_result = result
                            break
                    if lyric_result is None:
                        lyric_result = data["entries"][0]
                    
                    url = lyric_result["webpage_url"]
                    title = lyric_result.get("title", "Unknown title")
                    await processing_message.edit(content=f"Found song: `{title}\nNow adding to queue...`")
                else:
                    await message.channel.send("No search results found on YouTube")
                    return
                
                data = await loop.run_in_executor(
                    None,
                    lambda: ytdl.extract_info(url, download=False)
                )
                
                if not data.get("url"):
                    if "formats" in data and len(data["formats"]) > 0:
                        data["url"] = data["formats"][0]["url"]
                    else:
                        await message.channel.send("Error: Could not retrieve valid audio URL from the search")
                        return
                    
                song_info = {
                    "title": data.get("title", "Unknown title"),
                    "url": data.get("url", None),
                    "webpage_url": data.get("webpage_url", url)
                }
                
                await helper(message.guild.id, [song_info])

                voice_client = voice_clients.get(message.guild.id)
                if not voice_client or not voice_client.is_connected():
                    voice_client = await message.author.voice.channel.connect()
                    voice_clients[message.guild.id] = voice_client
                    
                if not voice_client.is_playing():
                    await play_next_song(message.guild.id)
      
            except Exception as e:
                print(e)
        
        if message.content.startswith("?addQueue") or message.content.startswith("?addqueue"):
            try:
                parts = message.content.split()
                if (len(parts) < 2):
                    await message.channel.send("Please provide a YouTube URL after `?addQueue`")
                    return

                url = parts[1]
                processing_message = await message.channel.send("Processing link, please wait...")
                loop = asyncio.get_event_loop()
                data = await loop.run_in_executor(
                    None,
                    lambda: ytdl.extract_info(url, download=False)
                )

                if "entries" in data:
                    await message.channel.send("Adding playlist to queue...")

                    for entry in data["entries"]:
                        if not entry:
                            continue

                        if "url" not in entry:
                            continue
                        
                        song_info = {
                            "title": entry.get("title", "Unknown title"),
                            "url": entry.get("url", None),
                            "webpage_url": entry.get("webpage_url", url)
                        }

                        if message.guild.id not in music_queues:
                            music_queues[message.guild.id] = asyncio.Queue()

                        await music_queues[message.guild.id].put(song_info)

                        await message.channel.send(f"Added to queue: {song_info['title']}")

                else:
                    song_info = {
                        "title": data.get("title", "Unknown title"),
                        "url": data.get("url", None),
                        "webpage_url": data.get("webpage_url", url)
                    }

                    if message.guild.id not in music_queues:
                        music_queues[message.guild.id] = asyncio.Queue()
                
                    await music_queues[message.guild.id].put(song_info)

                    await message.channel.send(f"Added to queue: {song_info['title']}")
            
            except Exception as e:
                print(e)

        if message.content.startswith("?queue") or message.content.startswith("?q"):
            try:
                guild_id = message.guild.id

                if guild_id not in music_queues:
                    await message.channel.send("No songs are in queue")
                    return
                current_song = currently_playing.get(guild_id, None)

                queue_list = list(music_queues[guild_id]._queue)

                msg = ""
                if current_song:
                    msg += f"**Currently Playing:**{current_song['title']}\n({current_song['webpage_url']})\n\n"
                else:
                    msg += "Nothing is currently playing.\n\n"

                if queue_list:
                    msg += "**Up next in queue:**\n"
                    for i, song_info in enumerate(queue_list, 1):
                        msg += f"{i}. {song_info['title']}\n({current_song['webpage_url']})\n"
                else:
                    msg += "No more songs are in the queue."

                await message.channel.send(msg)
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
                if message.guild.id in music_queues:
                    while not music_queues[message.guild.id].empty():
                        bin = music_queues[message.guild.id].get_nowait()
            except Exception as e:
                print(e)
        
        if message.content.startswith("?skip"):
            try:
                voice_clients[message.guild.id].stop()

                await message.channel.send("Skipped current song.")
            except Exception as e:
                print(e)

        if message.content.startswith("?clear") or message.content.startswith("?c"):
            try:
                if message.guild.id in music_queues:
                    while not music_queues[message.guild.id].empty():
                        _ = music_queues[message.guild.id].get_nowait()

                    await message.channel.send("Cleared queue")
                
            except Exception as e:
                print(e)

    client.run(TOKEN)