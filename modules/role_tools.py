import discord
from discord.ext import commands
from typing import List


class RoleTools(commands.Cog):
    """
    Discord role utility tools.

    Behavior:
        - Admin only
        - Ephemeral
        - Shows server members who do not have a selected role
        - Can optionally include bots
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # =========================
    # HELPERS
    # =========================
    def split_lines(self, lines: List[str], max_length: int = 1900) -> List[str]:
        chunks = []
        current = ""

        for line in lines:
            candidate = current + line + "\n"

            if len(candidate) > max_length:
                if current.strip():
                    chunks.append(current.strip())
                current = line + "\n"
            else:
                current = candidate

        if current.strip():
            chunks.append(current.strip())

        return chunks

    def member_sort_key(self, member: discord.Member):
        return (
            member.display_name.lower(),
            member.name.lower(),
            member.id
        )

    def format_member_line(self, index: int, member: discord.Member) -> str:
        return f"**{index}.** {member.mention} — `{member.id}`"

    def get_missing_role_members(
        self,
        guild: discord.Guild,
        role: discord.Role,
        include_bots: bool
    ) -> List[discord.Member]:
        members = []

        for member in guild.members:
            if not include_bots and member.bot:
                continue

            if role not in member.roles:
                members.append(member)

        members.sort(key=self.member_sort_key)

        return members


async def setup(bot: commands.Bot):
    await bot.add_cog(RoleTools(bot))
