import discord
from redbot.core import Config
from redbot.core import commands
from redbot.core import checks
from collections import Counter


defaults = {"room_size": 4, "combines_category": None}

# TODO list:
#   - team_manager_cog => don't hardcode tiers in for loop
#   X- set/save/update combine details (i.e. room size, combines category while active)
#   - room permissions ("League" role, GM, AGM, scout, mod, or admins may join)
#   X- listener behavior
#       - player join
#           X- maybe make new/move room (A: move player to new room, B: add 2nd room, move original)    
#           X- increase room size (x/4)
#       - player leave
#           X- maybe remove room
#           X- decrement room size (x/4)

class RankedRooms(commands.Cog):
    def __init__(self, bot):
        self.config = Config.get_conf(self, identifier=1234567892, force_registration=True)
        self.config.register_guild(**defaults)
        self.team_manager_cog = bot.get_cog("teamManager")
        self._combines_category_name = "Combine Rooms"

    @commands.command(aliases=["startcombines", "stopcombines"])
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def combines(self, ctx, action=None):
        """
        Creates rooms for combines, or tears them down depending on the action parameter
        
        Examples:
        [p]combines start
        [p]combines stop
        """
        if action in ["start", "create"]:
            done = await self._start_combines(ctx)
        elif action in ["stop", "teardown", "end"]:
            done = await self._stop_combines(ctx)
        else:
            done = await self._start_combines(ctx) # TODO: make parameter optional, should behave as a switch.
        
        if done:
            await ctx.send("Done")
        return
    
    @commands.command(aliases=["scrs", "setroomsize", "srs"])
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def set_combine_room_size(self, ctx, size: int):
        if size < 2:
            await ctx.send("No.")
            return False  
        combines_cat = await self._save_room_size(ctx.guild, size)
        if combines_cat:
            for vc in combines_cat.voice_channels:
                await self._adjust_room_tally(guild, vc)
        await ctx.send("Done")
        return True
    
    @commands.command(aliases=["crs", "roomsize", "rs"])
    @commands.guild_only()
    async def get_combine_room_size(self, ctx):
        size = await self._combines_room_size(ctx.guild)
        await ctx.send("Combines should have no more than {0} active players in them.".format(size))

    @commands.Cog.listener("on_voice_state_update")
    async def on_voice_state_update(self, member, before, after):
        response_channel = self._get_channel_by_name(member.guild, "tests")
        # await response_channel.send("VOICE ACTIVITY DETECTED")

        # ignore when activity is within the same room
        if before.channel == after.channel:
            return
        
        # Room joined:
        await self._member_joins_voice(member, after.channel)
        
        # Room left:
        await self._member_leaves_voice(member, before.channel) # TODO: consider disconnected case #@me what does that even mean? this structure should cover everything

    async def _start_combines(self, ctx):
        # check if combines are running already (maybe check config file)
        # create combines category
        combines_category = await self._add_category(ctx, self._combines_category_name)
        await self._save_combine_category(ctx.guild, combines_category)
        # create DYNAMIC ROOMS for each rank
        if combines_category:
            for tier in ["Minor", "Major"]:  # self.team_manager_cog.tiers(ctx): # TODO: Make sure this cog works
                await self._add_combines_voice(ctx.guild, tier)
                # name: <tier> combines: Octane (identifier?)
                # permissions:
                    # <tier> voice visible by <tier, admin, mod, GM, AGM, scout>
                # behavior: 
                    # (listener command) => if 5th joins room, send to waiting room/new room?
                    # allow 4 PLAYERS, but allow x scouts/GMs
            return True
        return False

    async def _stop_combines(self, ctx):
        # remove combines channels, category
        combines_category = await self._combines_category(ctx.guild)
        if combines_category:
            for channel in combines_category.channels:
                await channel.delete()
            await combines_category.delete()
            return True
        await ctx.send("Could not find combine rooms.")
        return False

    def _get_channel_by_name(self, guild: discord.Guild, name: str):
        for channel in guild.channels:
            if channel.name == name:
                return channel
    
    async def _add_category(self, ctx, name: str):
        category = await self._get_category_by_name(ctx.guild, name)
        if category:
            await ctx.send("A category with the name \"{0}\" already exists".format(name))
            return None
        category = await ctx.guild.create_category(name)
        return category

    async def _maybe_remove_combines_voice(self, guild: discord.Guild, voice_channel: discord.VoiceChannel):
        tier = self._get_voice_tier(voice_channel)
        category = await self._combines_category(guild)
        tier_voice_channels = []
        for vc in category.voice_channels:
            if tier in vc.name:
                tier_voice_channels.append(vc)
        
        if len(tier_voice_channels) > 1:
            await voice_channel.delete()
            return True
        max_size = self._combines_room_size(guild)
        rename = "{0} room 1 (0/{1})".format(tier, max_size)
        await voice_channel.edit(name=rename)

    async def _add_combines_voice(self, guild: discord.Guild, tier: str):
        # user_limit of 0 means there's no limit
        # determine position with same name +1
        category = await self._combines_category(guild)
        tier_rooms = []
        for vc in category.voice_channels:
            if tier in vc.name:
                tier_rooms.append(vc)

        room_makeable = False
        new_position = None
        new_room_number = 1
        while not room_makeable:
            room_makeable = True
            for vc in tier_rooms:
                i = vc.name.index("room ") + 5
                j = vc.name.index(" (")
                vc_room_num = int(vc.name[i:j])
                if vc_room_num == new_room_number:
                    new_room_number += 1
                    new_position = vc.position + 1
                    room_makeable = False
        
        max_size = await self._combines_room_size(guild)
        room_name = "{0} room {1} (0/{2})".format(tier, new_room_number, max_size)
        if not new_position:
            await category.create_voice_channel(room_name)
        else:
            await category.create_voice_channel(room_name, position=new_position)

    async def _member_joins_voice(self, member: discord.Member, voice_channel: discord.VoiceChannel):
        if voice_channel in (await self._combines_category(member.guild)).voice_channels:
            player_count = await self._adjust_room_tally(member.guild, voice_channel)
            if player_count == 1:
                tier = self._get_voice_tier(voice_channel)
                await self._add_combines_voice(member.guild, tier)
   
    async def _member_leaves_voice(self, member: discord.Member, voice_channel: discord.VoiceChannel):
        if voice_channel in (await self._combines_category(member.guild)).voice_channels:
            test_channel = self._get_channel_by_name(member.guild, "tests")
            player_count = await self._adjust_room_tally(member.guild, voice_channel)
            if player_count == 0:
                await self._maybe_remove_combines_voice(member.guild, voice_channel)
        
    async def _get_category_by_name(self, guild: discord.Guild, name: str): 
        for category in guild.categories:
            if category.name == name:
                return category
        return None
    
    async def _adjust_room_tally(self, guild: discord.Guild, voice_channel: discord.VoiceChannel):
        # possibility: only call this function when an active player triggers the call and/or make this an increment/decrement function
        fa_role = self._get_role_by_name(guild, "Free Agent")
        de_role = self._get_role_by_name(guild, "Draft Eligible")
        player_count = 0
        max_size = await self._combines_room_size(guild)
        for member in voice_channel.members:
            active_player = fa_role in member.roles or de_role in member.roles
            if active_player:
                player_count += 1
        
        name_base = voice_channel.name[:voice_channel.name.index(" (")]
        rename = "{0} ({1}/{2})".format(name_base, player_count, max_size)
        await voice_channel.edit(name=rename)
        return player_count

    def _get_role_by_name(self, guild: discord.Guild, name: str):
        for role in guild.roles:
            if role.name == name:
                return role
        return None
    
    def _get_voice_tier(self, voice_channel: discord.VoiceChannel):
        return voice_channel.name.split()[0]

    async def _combines_category(self, guild: discord.Guild):
        saved_combine_cat = await self.config.guild(guild).combines_category()
        for category in guild.categories:
            if category.id == saved_combine_cat:
                return category
        return None
    
    async def _save_combine_category(self, guild: discord.Guild, category: discord.CategoryChannel):
        await self.config.guild(guild).combines_category.set(category.id)
    
    async def _combines_room_size(self, guild):
        room_size = await self.config.guild(guild).room_size()
        return room_size if room_size else None

    async def _save_room_size(self, guild: discord.Guild, size: int):
        await self.config.guild(guild).room_size.set(size)
