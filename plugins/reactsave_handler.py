"""Handle reaction-based media saving."""
import logging

logger = logging.getLogger("reactsave_handler")

@bot.on("reaction")
async def on_reaction(ctx):
    """Extract and save media when someone reacts to a message."""
    try:
        logger.info(f"REACTION RECEIVED: emoji={ctx.event.text}, from={ctx.sender}")
        
        # Check if reactsave is enabled
        if not ctx.db.get("reactsave_enabled", False):
            logger.info("ReactSave is disabled")
            return
        
        # Get the original message
        original_msg = ctx.event.raw
        logger.info(f"Raw event type: {type(original_msg)}, raw: {original_msg}")
        
        if not original_msg or not isinstance(original_msg, dict):
            logger.warning(f"Invalid raw message: {original_msg}")
            await ctx.bot.send_message(f"{list(ctx.bot.owner_ids)[0]}@s.whatsapp.net", 
                                      f"✅ Reaction detected: {ctx.event.text}\n(Could not get message data)")
            return
        
        # Try to get message from raw
        msg = original_msg.get("message")
        logger.info(f"Message object: {msg}, keys: {list(msg.keys()) if msg and isinstance(msg, dict) else 'N/A'}")
        
        if not msg or not isinstance(msg, dict):
            logger.warning("No message dict found")
            await ctx.bot.send_message(f"{list(ctx.bot.owner_ids)[0]}@s.whatsapp.net", 
                                      f"✅ Reaction detected: {ctx.event.text}\n(No message content)")
            return
        
        # Check for media
        media_type = None
        
        if "viewOnceMessage" in msg:
            media_type = "🔐 ViewOnce"
        elif "imageMessage" in msg:
            media_type = "🖼️ Image"
        elif "videoMessage" in msg:
            media_type = "🎥 Video"
        elif "documentMessage" in msg:
            media_type = "📄 Document"
        elif "audioMessage" in msg:
            media_type = "🎵 Audio"
        else:
            logger.info(f"No media type matched. Keys: {list(msg.keys())}")
            await ctx.bot.send_message(f"{list(ctx.bot.owner_ids)[0]}@s.whatsapp.net", 
                                      f"✅ Reaction detected: {ctx.event.text}\nMessage type: {list(msg.keys())}")
            return
        
        owner_id = list(ctx.bot.owner_ids)[0] if ctx.bot.owner_ids else None
        dm_chat_id = f"{owner_id}@s.whatsapp.net"
        
        message = f"📥 {media_type} reacted with {ctx.event.text}"
        logger.info(f"Sending to DM: {message}")
        await ctx.bot.send_message(dm_chat_id, message)
        
    except Exception as e:
        logger.exception(f"Error in reaction handler: {e}")
        try:
            owner_id = list(ctx.bot.owner_ids)[0] if ctx.bot.owner_ids else None
            await ctx.bot.send_message(f"{owner_id}@s.whatsapp.net", f"❌ ReactSave Error: {str(e)}")
        except:
            pass