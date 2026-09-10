# -*- coding: utf-8 -*-
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv
from openai import AsyncOpenAI

from db import Database, RESOURCE_NAMES, total_for
import events, tickets, attendance, warehouses, workshops, settings_ui

load_dotenv()
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN', '').strip()
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '').strip()
OPENAI_MODEL = os.getenv('OPENAI_MODEL', 'gpt-5.6-luna').strip()
DATABASE_PATH = os.getenv('DATABASE_PATH', 'resources.db').strip()
LEGACY_ADMIN_ROLE_ID = int(os.getenv('ADMIN_ROLE_ID', '0') or 0)
OWNER_USER_ID = int(os.getenv('BOT_OWNER_ID', '766300799332122624') or 766300799332122624)
PILOT_GUILD_ID = int(os.getenv('PILOT_GUILD_ID', '0') or 0)


def parse_ids(raw):
    try:
        return [int(x) for x in json.loads(raw or '[]')]
    except Exception:
        return []


class GuildBotProxy:
    """Expose the normal bot API but bind .db to one guild's independent database."""
    def __init__(self, root, guild_id):
        self.root = root
        self.guild_id = int(guild_id)

    @property
    def db(self):
        return self.root.db_for(self.guild_id)

    def for_guild(self, guild_id):
        return self.root.for_guild(guild_id)

    async def is_global_admin(self, member):
        return await self.root.is_global_admin(member)

    async def is_attendance_admin(self, member):
        return await self.root.is_attendance_admin(member)

    async def is_employee(self, member):
        return await self.root.is_employee(member)

    async def require_admin(self, interaction):
        return await self.root.require_admin(interaction)

    async def require_att_admin(self, interaction):
        return await self.root.require_att_admin(interaction)

    def __getattr__(self, name):
        return getattr(self.root, name)


class ServerBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix=commands.when_mentioned, intents=intents)

        self.base_db = Database(DATABASE_PATH)
        self._dbs = {}
        self._db_initialized = set()
        self._persistent_registered = set()
        self.openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
        self.openai_model = OPENAI_MODEL
        self.pending_scans = set()
        self.owner_user_id = OWNER_USER_ID
        self.pilot_guild_id = PILOT_GUILD_ID

    def guild_db_path(self, guild_id):
        p = Path(DATABASE_PATH)
        suffix = p.suffix or '.db'
        stem = p.stem if p.suffix else p.name
        return str(p.with_name(f'{stem}_{int(guild_id)}{suffix}'))

    def db_for(self, guild_id):
        gid = int(guild_id)
        if gid not in self._dbs:
            self._dbs[gid] = Database(self.guild_db_path(gid))
        return self._dbs[gid]

    def for_guild(self, guild_id):
        return GuildBotProxy(self, int(guild_id))

    async def ensure_guild_db(self, guild_id):
        gid = int(guild_id)
        if gid not in self._db_initialized:
            await self.db_for(gid).init()
            self._db_initialized.add(gid)
        return self.db_for(gid)

    async def resolve_pilot_guild(self):
        # 1) .env wins.
        if self.pilot_guild_id:
            await self.base_db.set_meta('pilot_guild_id', self.pilot_guild_id)
        else:
            # 2) Previously bound server.
            saved = int(await self.base_db.get_meta('pilot_guild_id', '0') or 0)
            if saved:
                self.pilot_guild_id = saved

        # 3) Infer the old/main server from legacy configured channels.
        if not self.pilot_guild_id:
            for key in (
                'event_panel_channel_id', 'panel_channel_id', 'log_channel_id',
                'ticket_panel_channel_id', 'attendance_panel_channel_id',
                'warehouse_panel_channel_id'
            ):
                try:
                    cid = int(await self.base_db.get_setting(key, '0') or 0)
                except Exception:
                    cid = 0
                if not cid:
                    continue
                for guild in self.guilds:
                    if guild.get_channel(cid):
                        self.pilot_guild_id = guild.id
                        break
                if self.pilot_guild_id:
                    break

        # 4) Safe fallback: a server actually owned by pilot, or the only server.
        if not self.pilot_guild_id:
            owned = [g for g in self.guilds if g.owner_id == self.owner_user_id]
            if len(owned) == 1:
                self.pilot_guild_id = owned[0].id
            elif len(self.guilds) == 1:
                self.pilot_guild_id = self.guilds[0].id

        if self.pilot_guild_id:
            await self.base_db.set_meta('pilot_guild_id', self.pilot_guild_id)
            # Preserve the old bot data for the main server on first upgrade.
            target = Path(self.guild_db_path(self.pilot_guild_id))
            source = Path(DATABASE_PATH)
            if source.exists() and not target.exists():
                try:
                    shutil.copy2(source, target)
                except OSError as exc:
                    print('legacy db copy', repr(exc))

    async def bind_pilot_guild_if_needed(self, interaction):
        if interaction.user.id != self.owner_user_id or not interaction.guild:
            return False
        if not self.pilot_guild_id:
            self.pilot_guild_id = interaction.guild.id
            await self.base_db.set_meta('pilot_guild_id', self.pilot_guild_id)
        return interaction.guild.id == self.pilot_guild_id

    async def setup_hook(self):
        await self.base_db.init()
        # Ticket-close uses a static custom_id. Its callback resolves the guild at runtime.
        self.add_view(tickets.TicketCloseView(self))
        await self.tree.sync()
        self.board_clock.start()

    async def register_persistent_views(self, guild):
        gb = self.for_guild(guild.id)
        db = gb.db

        async def add(kind, message_id, view):
            mid = int(message_id or 0)
            if not mid or view is None:
                return
            key = (guild.id, kind, mid)
            if key in self._persistent_registered:
                return
            try:
                self.add_view(view, message_id=mid)
                self._persistent_registered.add(key)
            except Exception as exc:
                print('persistent view', kind, repr(exc))

        event_mid = await db.get_setting('event_panel_message_id', '0')
        await add('event', event_mid, await events.panel_view(gb))

        ticket_mid = await db.get_setting('ticket_panel_message_id', '0')
        ticket_types = await db.ticket_types(True)
        if ticket_types:
            await add('tickets', ticket_mid, tickets.TicketPanelView(gb, ticket_types))

        attendance_mid = await db.get_setting('attendance_panel_message_id', '0')
        await add('attendance', attendance_mid, attendance.AttendancePanelView(gb))

        warehouse_mid = await db.get_setting('warehouse_panel_message_id', '0')
        warehouse_rows = await db.warehouse_locations(True)
        if warehouse_rows:
            await add('warehouses', warehouse_mid, warehouses.WarehousePanelView(gb, warehouse_rows))

        workshop_mid = await db.get_setting('workshop_panel_message_id', '0')
        await add('workshops', workshop_mid, workshops.WorkshopPanelView(gb))

    async def is_global_admin(self, member):
        if getattr(member, 'id', None) == self.owner_user_id:
            return True
        if not isinstance(member, discord.Member):
            return False
        if member.guild_permissions.administrator:
            return True
        if LEGACY_ADMIN_ROLE_ID and any(r.id == LEGACY_ADMIN_ROLE_ID for r in member.roles):
            return True
        await self.ensure_guild_db(member.guild.id)
        roleids = parse_ids(await self.db_for(member.guild.id).get_setting('bot_admin_role_ids', '[]'))
        return any(r.id in roleids for r in member.roles)

    async def is_attendance_admin(self, member):
        if await self.is_global_admin(member):
            return True
        if not isinstance(member, discord.Member):
            return False
        roleids = parse_ids(await self.db_for(member.guild.id).get_setting('attendance_admin_role_ids', '[]'))
        return any(r.id in roleids for r in member.roles)

    async def is_employee(self, member):
        if not isinstance(member, discord.Member):
            return False
        await self.ensure_guild_db(member.guild.id)
        roleids = parse_ids(await self.db_for(member.guild.id).get_setting('attendance_employee_role_ids', '[]'))
        return bool(roleids) and any(r.id in roleids for r in member.roles)

    async def require_admin(self, interaction):
        if await self.is_global_admin(interaction.user):
            return True
        if interaction.response.is_done():
            await interaction.followup.send('⛔ هذا الأمر مخصص للإدارة فقط.', ephemeral=True)
        else:
            await interaction.response.send_message('⛔ هذا الأمر مخصص للإدارة فقط.', ephemeral=True)
        return False

    async def require_att_admin(self, interaction):
        if await self.is_attendance_admin(interaction.user):
            return True
        if interaction.response.is_done():
            await interaction.followup.send('⛔ هذا الإجراء مخصص لإدارة الموظفين.', ephemeral=True)
        else:
            await interaction.response.send_message('⛔ هذا الإجراء مخصص لإدارة الموظفين.', ephemeral=True)
        return False

    @tasks.loop(minutes=5)
    async def board_clock(self):
        for guild in self.guilds:
            try:
                await self.ensure_guild_db(guild.id)
                gb = self.for_guild(guild.id)
                await attendance.refresh_staff(gb, guild, False)
                await workshops.refresh_leaderboard(gb, guild, False)
            except Exception as exc:
                print('board refresh', repr(exc))

    @board_clock.before_loop
    async def before_clock(self):
        await self.wait_until_ready()


if not DISCORD_TOKEN:
    raise RuntimeError('DISCORD_TOKEN is missing. Put it in .env')
if not OPENAI_API_KEY:
    raise RuntimeError('OPENAI_API_KEY is missing. Put it in .env')

bot = ServerBot()


@bot.event
async def on_ready():
    print(f'Logged in as {bot.user} (ID: {bot.user.id})')
    await bot.resolve_pilot_guild()
    for guild in bot.guilds:
        try:
            await bot.ensure_guild_db(guild.id)
            gb = bot.for_guild(guild.id)
            await events.publish(gb, guild)
            await tickets.refresh_panel(gb, guild, False)
            await attendance.refresh_status(gb, guild, False)
            await attendance.refresh_staff(gb, guild, False)
            await warehouses.refresh_panel(gb, guild, False)
            await workshops.refresh_panel(gb, guild, False)
            await workshops.refresh_leaderboard(gb, guild, False)
            await bot.register_persistent_views(guild)
        except Exception as exc:
            print('startup refresh', guild.id, repr(exc))


@bot.event
async def on_guild_join(guild):
    try:
        await bot.ensure_guild_db(guild.id)
        print(f'Initialized independent database for guild {guild.id}')
    except Exception as exc:
        print('guild init', repr(exc))


@bot.event
async def on_member_update(before, after):
    if before.roles != after.roles:
        try:
            gb = bot.for_guild(after.guild.id)
            await attendance.refresh_staff(gb, after.guild, False)
        except Exception:
            pass


@bot.event
async def on_member_remove(member):
    try:
        gb = bot.for_guild(member.guild.id)
        await attendance.refresh_staff(gb, member.guild, False)
    except Exception:
        pass


class PilotPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label='تحديث', emoji='🔄', style=discord.ButtonStyle.primary)
    async def refresh(self, i, b):
        if not await bot.bind_pilot_guild_if_needed(i):
            await i.response.send_message('هذا الأمر لـ pilot فقط.', ephemeral=True)
            return
        await i.response.edit_message(embeds=pilot_embeds(), view=self)


def pilot_embeds():
    status = '🟢 شغال' if bot.is_ready() and not bot.is_closed() else '🔴 متوقف'
    latency = round(bot.latency * 1000) if bot.latency >= 0 else 0
    first = discord.Embed(
        title='🛡️ لوحة pilot — حالة البوت',
        description=(
            f'**الحالة:** {status}\n'
            f'**Ping:** `{latency} ms`\n'
            f'**عدد السيرفرات:** **{len(bot.guilds)}**\n'
            f'**السيرفر الرئيسي:** `{bot.pilot_guild_id or 0}`'
        )
    )
    lines = []
    for guild in sorted(bot.guilds, key=lambda g: g.name.casefold()):
        state = '🔴 غير متاح' if guild.unavailable else '🟢 شغال'
        lines.append(f"{state} **{guild.name}** — `{guild.id}` — {guild.member_count or 0} عضو")
    if not lines:
        first.add_field(name='السيرفرات', value='لا يوجد', inline=False)
        return [first]

    embeds = [first]
    chunk = []
    length = 0
    part = 1
    for line in lines:
        if chunk and (len(chunk) >= 25 or length + len(line) > 3600):
            embeds.append(discord.Embed(title=f'🌐 السيرفرات — {part}', description='\n'.join(chunk)))
            part += 1
            chunk = []
            length = 0
        chunk.append(line)
        length += len(line) + 1
    if chunk:
        embeds.append(discord.Embed(title=f'🌐 السيرفرات — {part}', description='\n'.join(chunk)))
    return embeds[:10]


@bot.tree.command(name='pilot', description='لوحة خاصة بصاحب البوت فقط.')
async def pilot_cmd(i: discord.Interaction):
    if not await bot.bind_pilot_guild_if_needed(i):
        await i.response.send_message('هذا الأمر لـ pilot فقط.', ephemeral=True)
        return
    await i.response.send_message(embeds=pilot_embeds(), view=PilotPanelView(), ephemeral=True)


@bot.tree.command(name='settings', description='فتح لوحة إعدادات البوت الخاصة بهذا السيرفر.')
async def settings_cmd(i: discord.Interaction):
    if not i.guild:
        await i.response.send_message('داخل السيرفر فقط.', ephemeral=True)
        return
    if not await bot.require_admin(i):
        return
    await bot.ensure_guild_db(i.guild_id)
    gb = bot.for_guild(i.guild_id)
    await i.response.send_message(embed=settings_ui.home_embed(), view=settings_ui.SettingsHome(gb), ephemeral=True)


@bot.tree.command(name='إنشاء_فعالية', description='إنشاء وبدء فعالية جديدة مع الرسالة والشروط والرومات.')
@app_commands.describe(name='اسم الفعالية', message='رسالة لوحة الفعالية', terms='شروط الفعالية', panel_channel='روم لوحة الفعالية', leaderboard_channel='روم المتصدرين', log_channel='روم لوق الصور', image_url='رابط صورة اختياري')
async def create_event(i: discord.Interaction, name: str, message: str, terms: str, panel_channel: discord.TextChannel, leaderboard_channel: discord.TextChannel, log_channel: discord.TextChannel, image_url: Optional[str] = None):
    if not i.guild or not await bot.require_admin(i):
        return
    gb = bot.for_guild(i.guild_id)
    db = gb.db
    if await db.is_active():
        await i.response.send_message('⚠️ توجد فعالية نشطة. أنهها أولًا.', ephemeral=True)
        return
    if image_url and not image_url.startswith(('http://', 'https://')):
        await i.response.send_message('رابط الصورة غير صحيح.', ephemeral=True)
        return
    await db.set_settings({'event_name': name.strip(), 'event_description': message.strip(), 'event_terms': terms.strip(), 'event_image_url': image_url or '', 'event_panel_channel_id': panel_channel.id, 'event_leaderboard_channel_id': leaderboard_channel.id, 'log_channel_id': log_channel.id, 'event_panel_message_id': '0', 'event_leaderboard_message_id': '0'})
    started, eid = await db.start_event()
    if not started:
        await i.response.send_message(f'⚠️ توجد فعالية نشطة بالفعل #{eid}.', ephemeral=True)
        return
    await i.response.defer(ephemeral=True, thinking=True)
    ok, text = await events.publish(gb, i.guild)
    await i.followup.send(f"{'✅' if ok else '⚠️'} تم إنشاء **{name}** كفعالية #{eid}.\n{text}", ephemeral=True)


@bot.tree.command(name='بداية_الفعالية', description='بدء فعالية بالإعدادات الحالية.')
async def start_event(i: discord.Interaction):
    if not i.guild or not await bot.require_admin(i):
        return
    gb = bot.for_guild(i.guild_id)
    ok, eid = await gb.db.start_event()
    if not ok:
        await i.response.send_message(f'⚠️ توجد فعالية نشطة بالفعل #{eid}.', ephemeral=True)
        return
    await i.response.defer(ephemeral=True, thinking=True)
    _, text = await events.publish(gb, i.guild)
    await i.followup.send(f'✅ بدأت الفعالية #{eid}.\n{text}', ephemeral=True)


@bot.tree.command(name='إنهاء_الفعالية', description='إنهاء الفعالية وحفظ النتائج وتصفير لوحة المتصدرين.')
async def end_event(i: discord.Interaction):
    if not i.guild or not await bot.require_admin(i):
        return
    gb = bot.for_guild(i.guild_id)
    if not await gb.db.is_active():
        await i.response.send_message('لا توجد فعالية نشطة.', ephemeral=True)
        return
    e = discord.Embed(title='⚠️ تأكيد إنهاء الفعالية', description='سيتم حفظ النتائج ثم **تصفير جميع نقاط لوحة المتصدرين**.')
    await i.response.send_message(embed=e, view=events.EndEventView(gb, i.user.id), ephemeral=True)


@bot.tree.command(name='لوحة', description='إرسال أو تحديث لوحة الفعالية والمتصدرين.')
async def event_panel(i: discord.Interaction):
    if not i.guild or not await bot.require_admin(i):
        return
    gb = bot.for_guild(i.guild_id)
    await i.response.defer(ephemeral=True, thinking=True)
    ok, text = await events.publish(gb, i.guild)
    await i.followup.send(('✅ ' if ok else '⚠️ ') + text, ephemeral=True)


@bot.tree.command(name='احصائيات', description='عرض إحصائيات موارد عضو أو جميع المشاركين.')
@app_commands.describe(member='اختياري: عضو محدد')
async def stats(i: discord.Interaction, member: Optional[discord.Member] = None):
    if not i.guild or not await bot.require_admin(i):
        return
    gb = bot.for_guild(i.guild_id)
    if member:
        await i.response.send_message(embed=events.points_embed(member, await gb.db.get_balance(member.id)), ephemeral=True)
        return
    rows = await gb.db.get_balances()
    if not rows:
        await i.response.send_message('لا توجد إحصائيات.', ephemeral=True)
        return
    medals = ['🥇', '🥈', '🥉']
    lines = [f"{medals[x] if x < 3 else f'**{x + 1}.**'} <@{r['user_id']}> — **{total_for(r):,}**" for x, r in enumerate(rows[:25])]
    await i.response.send_message(embed=discord.Embed(title='📊 إحصائيات الفعالية', description='\n'.join(lines)), ephemeral=True)


RESOURCE_CHOICES = [app_commands.Choice(name=x.title() if x != 'metalscrap' else 'Metalscrap', value=x) for x in RESOURCE_NAMES]


@bot.tree.command(name='اضافة', description='إضافة نقاط أو مورد لعضو في الفعالية.')
@app_commands.describe(member='العضو', amount='الكمية', resource='مورد اختياري')
@app_commands.choices(resource=RESOURCE_CHOICES)
async def add_points(i: discord.Interaction, member: discord.Member, amount: app_commands.Range[int, 1, 2_000_000_000], resource: Optional[app_commands.Choice[str]] = None):
    if not i.guild or not await bot.require_admin(i):
        return
    gb = bot.for_guild(i.guild_id)
    if not await gb.db.is_active():
        await i.response.send_message('🔒 لا توجد فعالية نشطة.', ephemeral=True)
        return
    eid = await gb.db.current_event_id()
    ok = await gb.db.adjust(eid, i.user.id, member.id, amount, resource.value if resource else None)
    if not ok:
        await i.response.send_message('تعذر التعديل.', ephemeral=True)
        return
    bal = await gb.db.get_balance(member.id)
    await i.response.send_message(f'✅ تم التعديل لـ {member.mention}. المجموع: **{total_for(bal):,}**', ephemeral=True)
    await events.refresh_leaderboard(gb, i.guild, True)


@bot.tree.command(name='خصم', description='خصم من مجموع عضو في الفعالية.')
async def deduct(i: discord.Interaction, member: discord.Member, amount: app_commands.Range[int, 1, 2_000_000_000]):
    if not i.guild or not await bot.require_admin(i):
        return
    gb = bot.for_guild(i.guild_id)
    if not await gb.db.is_active():
        await i.response.send_message('🔒 لا توجد فعالية نشطة.', ephemeral=True)
        return
    eid = await gb.db.current_event_id()
    await gb.db.adjust(eid, i.user.id, member.id, -amount, None)
    bal = await gb.db.get_balance(member.id)
    await i.response.send_message(f'✅ تم الخصم من {member.mention}. المجموع: **{total_for(bal):,}**', ephemeral=True)
    await events.refresh_leaderboard(gb, i.guild, True)


@bot.tree.command(name='ملاحظة', description='إضافة أو تعديل ملاحظة بجانب الموظف؛ اتركها فارغة للحذف.')
@app_commands.describe(member='الموظف', note='الملاحظة أو اتركها فارغة للحذف')
async def note(i: discord.Interaction, member: discord.Member, note: Optional[str] = None):
    if not i.guild or not await bot.require_att_admin(i):
        return
    gb = bot.for_guild(i.guild_id)
    await gb.db.set_note(member.id, note, i.user.id)
    await attendance.refresh_staff(gb, i.guild, True)
    await i.response.send_message(f"✅ تم {'حفظ' if note and note.strip() else 'حذف'} ملاحظة {member.mention}.", ephemeral=True)
    await attendance.staff_log(gb, i.guild, discord.Embed(title='📝 ملاحظة موظف', description=f"الموظف: {member.mention}\nالإداري: {i.user.mention}\nالملاحظة: {note or 'تم الحذف'}", timestamp=datetime.now(timezone.utc)))


@bot.tree.command(name='رسالة_موظف', description='إرسال رسالة خاصة لموظف عن طريق البوت.')
@app_commands.describe(member='الموظف', message='نص الرسالة', title='عنوان اختياري')
async def staff_message(i: discord.Interaction, member: discord.Member, message: str, title: Optional[str] = None):
    if not i.guild or not await bot.require_att_admin(i):
        return
    gb = bot.for_guild(i.guild_id)
    if not await gb.is_employee(member):
        await i.response.send_message('⚠️ العضو لا يحمل رتبة الموظف المحددة.', ephemeral=True)
        return
    e = discord.Embed(title=title or '📩 رسالة من الإدارة', description=message, timestamp=datetime.now(timezone.utc))
    e.set_footer(text=f'السيرفر: {i.guild.name}')
    try:
        await member.send(embed=e)
        delivered = True
    except discord.HTTPException:
        delivered = False
    await i.response.send_message('✅ تم إرسال الرسالة.' if delivered else '⚠️ تعذر الإرسال؛ الخاص قد يكون مقفلًا.', ephemeral=True)
    log = discord.Embed(title='📨 رسالة إدارية لموظف', description=f"إلى: {member.mention}\nبواسطة: {i.user.mention}\nالحالة: {'وصلت' if delivered else 'تعذر الإرسال'}", timestamp=datetime.now(timezone.utc))
    log.add_field(name='الرسالة', value=message[:1024], inline=False)
    await attendance.staff_log(gb, i.guild, log)


@bot.tree.command(name='تصفير_الحضور', description='تصفير ساعات الحضور وإنهاء الجلسات الحالية.')
async def reset_attendance_cmd(i: discord.Interaction):
    if not i.guild or not await bot.require_att_admin(i):
        return
    gb = bot.for_guild(i.guild_id)
    await i.response.send_message('⚠️ سيتم تصفير جميع ساعات الحضور وإنهاء الجلسات الحالية. متأكد؟', view=settings_ui.AttendanceResetConfirm(gb, i.user.id), ephemeral=True)


@bot.tree.command(name='تصفير_الورش', description='تصفير ترتيب أكثر المتفاعلين في نظام الورش.')
async def reset_workshops_cmd(i: discord.Interaction):
    if not i.guild or not await bot.require_admin(i):
        return
    gb = bot.for_guild(i.guild_id)
    await i.response.send_message('⚠️ هل تريد تصفير ترتيب أكثر المتفاعلين للورش؟', view=settings_ui.WorkshopResetConfirm(gb, i.user.id), ephemeral=True)


def help_embed():
    return discord.Embed(
        title='📘 أنظمة البوت',
        description=(
            '**/settings** لوحة التحكم الخاصة بكل سيرفر.\n'
            '**/إنشاء_فعالية** إنشاء وبدء فعالية.\n'
            '**/إنهاء_الفعالية** حفظ النتائج والتصفير.\n'
            '**/احصائيات /اضافة /خصم** إدارة الموارد.\n'
            '**/ملاحظة** ملاحظات لوحة الموظفين.\n'
            '**/رسالة_موظف** إرسال رسالة خاصة.\n'
            '**/تصفير_الحضور** تصفير ساعات الموظفين.\n'
            '**/تصفير_الورش** تصفير ترتيب تفاعل الورش.\n\n'
            'لوحات التذاكر والحضور والموظفين والمخازن والورش تضبط من /settings.'
        )
    )


@bot.tree.command(name='مساعدة', description='عرض ملخص أنظمة البوت.')
async def help_cmd(i: discord.Interaction):
    await i.response.send_message(embed=help_embed(), ephemeral=True)


@bot.tree.command(name='مساعدة_الفعالية', description='عرض شرح مختصر لأنظمة وأوامر البوت.')
async def legacy_event_help(i: discord.Interaction):
    await i.response.send_message(embed=help_embed(), ephemeral=True)


@bot.tree.error
async def tree_error(i, error):
    print('slash error', repr(error))
    text = 'حدث خطأ أثناء تنفيذ الأمر.'
    if i.response.is_done():
        await i.followup.send(text, ephemeral=True)
    else:
        await i.response.send_message(text, ephemeral=True)


bot.run(DISCORD_TOKEN)
