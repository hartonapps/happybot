"""Handle reaction-based media saving."""
import json
import subprocess


@bot.on("reaction")
async def on_reaction(ctx):
    """Extract and save media when someone reacts to a message."""
    if not ctx.db.get("reactsave_enabled", False):
        return
    
    # Get the original message from raw event
    original_msg = ctx.event.raw
    if not original_msg or "message" not in original_msg:
        return
    
    msg = original_msg["message"]
    
    # Check if it has media (viewonce, image, video, document, etc.)
    media_type = None
    if "viewOnceMessage" in msg:
        media_type = "viewonce"
        actual_msg = msg["viewOnceMessage"].get("message", {})
    elif "imageMessage" in msg:
        media_type = "image"
        actual_msg = msg
    elif "videoMessage" in msg:
        media_type = "video"
        actual_msg = msg
    elif "documentMessage" in msg:
        media_type = "document"
        actual_msg = msg
    else:
        return
    
    # Send notification to owner
    caption = ""
    if "imageMessage" in actual_msg:
        caption = actual_msg["imageMessage"].get("caption", "")
    elif "videoMessage" in actual_msg:
        caption = actual_msg["videoMessage"].get("caption", "")
    
    await ctx.send(f"📥 {media_type.upper()} saved from {ctx.sender}\n{caption if caption else '(no caption)'}")
