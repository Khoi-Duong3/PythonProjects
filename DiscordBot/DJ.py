import discord
import os
import asyncio
from dotenv import load_dotenv
import yt_dlp

def run_bot():
    # Load token and configure Discord client
    load_dotenv()
    TOKEN = os.getenv("discord_token")
    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)

    # State
    voice_clients = {}
    music_queues = {}
    currently_playing = {}

    # ── yt-dlp options ─────────────────────────────────────────────────────────
    yt_dl_options = {
        "format": "bestaudio/best",
        "default_search": "auto",   # URLs → direct; search terms → YouTube search
        "noplaylist": True          # Always grab a single video
    }
    ytdl = yt_dlp.YoutubeDL(yt_dl_options)

    # ffmpeg options for reconnect logic
    ffmpeg_options = {
        "options": "-vn",
        "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
    }

    @client.event
    async def on_ready():
        print(f"{client.user} is now jamming")

    # Play next song in queue for a guild
    async def play_next_song(guild_id):
        voice_client = voice_clients.get(guild_id)
        if not voice_client or not voice_client.is_connected():
            return

        queue = music_queues.get(guild_id)
        if not queue or queue.empty():
            return

        song_info = await queue.get()
        currently_playing[guild_id] = song_info

        player = discord.FFmpegPCMAudio(song_info["url"], **ffmpeg_options)

        def after_playing(error):
            if error:
                print(f"Error in playback: {error}")
            coro = play_next_song(guild_id)
            fut = asyncio.run_coroutine_threadsafe(coro, client.loop)
            try:
                fut.result()
            except Exception as e:
                print(e)

        voice_client.play(player, after=after_playing)

    # Helper to prepend new songs to the front of the queue
    async def helper(guild_id, new_songs):
        if guild_id not in music_queues:
            music_queues[guild_id] = asyncio.Queue()

        # drain old queue
        old_queue = []
        while not music_queues[guild_id].empty():
            old_queue.append(await music_queues[guild_id].get())

        # put new songs first
        for song in new_songs:
            await music_queues[guild_id].put(song)
        # then re-enqueue old songs
        for song in old_queue:
            await music_queues[guild_id].put(song)

    @client.event
    async def on_message(message):
        if message.author == client.user:
            return

        # Play Command 
        if message.content.startswith("?play"):
            try:
                if not message.author.voice or not message.author.voice.channel:
                    await message.channel.send("You must be in a voice channel to play music")
                    return

                command_text = message.content[len("?play"):].strip()
                if not command_text:
                    await message.channel.send("Please provide a song name and artist after `?play`.")
                    return

                # Build the query (no "ytsearch:" prefix)
                if " by " in command_text.lower():
                    song_name, artist_name = command_text.split(" by ", 1)
                    search_query = f"{song_name.strip()} by {artist_name.strip()} lyrics"
                else:
                    search_query = command_text

                processing_message = await message.channel.send(f"Searching for `{command_text}` on YouTube...")
                loop = asyncio.get_running_loop()

                # Perform search or direct URL fetch
                data = await loop.run_in_executor(
                    None,
                    lambda: ytdl.extract_info(search_query, download=False)
                )

                if "entries" in data:
                    entries = data["entries"] or []
                    if not entries:
                        await message.channel.send("No search results")
                        return
                    video = next((e for e in entries if "lyric" in e.get("title","").lower()), entries[0])
                else:
                    video = data
                
                url = video["webpage_url"]
                title = video.get("title", "Unknown title")
                await processing_message.edit(content=f"Found: **{title}**\nAdding to queue…")

                # Now extract the actual audio URL
                data = await loop.run_in_executor(
                    None,
                    lambda: ytdl.extract_info(url, download=False)
                )

                audio_url = data.get("url") or data["formats"][0]["url"]
                song_info = {
                    "title": data.get("title", "Unknown title"),
                    "url": audio_url,
                    "webpage_url": data.get("webpage_url", url)
                }
                
                # Enqueue and start playback if idle
                await helper(message.guild.id, [song_info])
                voice_client = voice_clients.get(message.guild.id)
                if not voice_client or not voice_client.is_connected():
                    voice_client = await message.author.voice.channel.connect()
                    voice_clients[message.guild.id] = voice_client
                if not voice_client.is_playing():
                    await play_next_song(message.guild.id)

            except Exception as e:
                print(e)

        # Add to Queue Command 
        if message.content.startswith("?add"):
            try:
                if not message.author.voice or not message.author.voice.channel:
                    await message.channel.send("You must be in a voice channel to add music")
                    return

                command_text = message.content[len("?add"):].strip()
                if not command_text:
                    await message.channel.send("Please provide a song name and artist after `?add`.")
                    return

                # Build the query (no "ytsearch:" prefix)
                if " by " in command_text.lower():
                    song_name, artist_name = command_text.split(" by ", 1)
                    search_query = f"{song_name.strip()} by {artist_name.strip()} lyrics"
                else:
                    search_query = command_text

                processing_message = await message.channel.send(f"Searching for `{command_text}` on YouTube...")
                loop = asyncio.get_running_loop()
                data = await loop.run_in_executor(
                    None,
                    lambda: ytdl.extract_info(search_query, download=False)
                )

                if "entries" in data:
                    entries = data["entries"] or []
                    if not entries:
                        await message.channel.send("No search results found")
                        return
                    
                    video = next((entry for entry in entries if 'lyric' in entry.get("title", "").lower()),
                                 entries[0]
                            )
                else:
                    video = data
                
                url = video["webpage_url"]
                title = video.get("title", "Unknown title")
                await processing_message.edit(content=f"Found: **{title}**\nAdding to queue…")
                audio_url = data.get("url") or data["formats"][0]["url"]

                song_info = {
                    "title": title,
                    "url": audio_url,
                    "webpage_url": url
                }

                # Simply enqueue (no helper—add to back of queue)
                if message.guild.id not in music_queues:
                    music_queues[message.guild.id] = asyncio.Queue()
                await music_queues[message.guild.id].put(song_info)

                voice_client = voice_clients.get(message.guild.id)
                if not voice_client or not voice_client.is_connected():
                    voice_client = await message.author.voice.channel.connect()
                    voice_clients[message.guild.id] = voice_client
                if not voice_client.is_playing():
                    await play_next_song(message.guild.id)

            except Exception as e:
                print(e)

        # Queue Display 
        if message.content.startswith("?queue") or message.content.startswith("?q"):
            try:
                guild_id = message.guild.id
                queue = music_queues.get(guild_id)
                if not queue or queue.empty():
                    await message.channel.send("No songs are in queue.")
                    return

                current = currently_playing.get(guild_id)
                entries = list(queue._queue)
                msg = ""
                if current:
                    msg += f"**Currently Playing:** {current['title']}\n({current['webpage_url']})\n\n"
                else:
                    msg += "Nothing is currently playing.\n\n"

                if entries:
                    msg += "**Up next:**\n"
                    for i, s in enumerate(entries, start=1):
                        msg += f"{i}. {s['title']}\n({s['webpage_url']})\n"
                await message.channel.send(msg)

            except Exception as e:
                print(e)

        # Pause / Resume / Stop / Skip / Clear 
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
                vc = voice_clients[message.guild.id]
                vc.stop()
                await vc.disconnect()
                # clear queue
                if message.guild.id in music_queues:
                    while not music_queues[message.guild.id].empty():
                        await music_queues[message.guild.id].get()
            except Exception as e:
                print(e)

        if message.content.startswith("?skip"):
            try:
                vc = voice_clients[message.guild.id]
                vc.stop()
                await message.channel.send("Skipped current song.")
            except Exception as e:
                print(e)

        if message.content.startswith("?clear") or message.content.startswith("?c"):
            try:
                if message.guild.id in music_queues:
                    while not music_queues[message.guild.id].empty():
                        await music_queues[message.guild.id].get()
                    await message.channel.send("Cleared queue.")
            except Exception as e:
                print(e)

    client.run(TOKEN)