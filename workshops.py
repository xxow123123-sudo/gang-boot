# -*- coding: utf-8 -*-
import asyncio
import io
from datetime import datetime, timezone

import discord


def image_attachment(a):
    if a.content_type and a.content_type.startswith('image/'):
        return True
    suffix = a.filename.lower().rsplit('.', 1)[-1] if '.' in a.filename else ''
    return suffix in {'png', 'jpg', 'jpeg', 'webp'}


async def panel_embed(bot):
    title = await bot.db.get_setting('workshop_panel_title', '🛠️ نظام الورش')
    desc = await bot.db.get_setting('workshop_panel_description', 'اضغط الزر وسجل الخدمة التي قمت ببيعها.')
    e = discord.Embed(title=title[:256], description=desc[:4000])
    image = (await bot.db.get_setting('workshop_panel_image_url', '')).strip()
    if image.startswith(('http://', 'https://')):
        e.set_image(url=image)
    e.add_field(
        name='الخدمات',
        value='• تعديل مركبة\n• بيع عدة تصليح',
        inline=False,
    )
    e.set_footer(text='يتم احتساب كل عملية معتمدة كنقطة تفاعل واحدة.')
    return e


async def refresh_panel(bot, guild, create=False):
    cid = int(await bot.db.get_setting('workshop_panel_channel_id', '0') or 0)
    ch = guild.get_channel(cid)
    if not isinstance(ch, discord.TextChannel):
        return False, 'حدد روم لوحة الورش أولًا.'
    mid = int(await bot.db.get_setting('workshop_panel_message_id', '0') or 0)
    msg = None
    if mid:
        try:
            msg = await ch.fetch_message(mid)
        except discord.HTTPException:
            pass
    view = WorkshopPanelView(bot)
    if msg:
        await msg.edit(embed=await panel_embed(bot), view=view)
    elif create:
        msg = await ch.send(embed=await panel_embed(bot), view=view)
        await bot.db.set_setting('workshop_panel_message_id', msg.id)
    return True, 'تم تحديث لوحة الورش.'


async def leaderboard_embed(bot):
    rows = await bot.db.workshop_leaderboard(25)
    medals = ['🥇', '🥈', '🥉']
    lines = []
    for index, row in enumerate(rows):
        prefix = medals[index] if index < 3 else f'**{index + 1}.**'
        lines.append(f"{prefix} <@{row['user_id']}> — **{int(row['total']):,}** خدمة")
    e = discord.Embed(
        title='🏆 أكثر المتفاعلين — الورش',
        description='\n'.join(lines) if lines else 'لا توجد عمليات مسجلة حاليًا.',
    )
    e.set_footer(text='تتحدث تلقائيًا بعد كل عملية معتمدة.')
    return e


async def refresh_leaderboard(bot, guild, create=False):
    cid = int(await bot.db.get_setting('workshop_leaderboard_channel_id', '0') or 0)
    ch = guild.get_channel(cid)
    if not isinstance(ch, discord.TextChannel):
        return False, 'حدد روم لوحة أكثر المتفاعلين للورش.'
    mid = int(await bot.db.get_setting('workshop_leaderboard_message_id', '0') or 0)
    msg = None
    if mid:
        try:
            msg = await ch.fetch_message(mid)
        except discord.HTTPException:
            pass
    e = await leaderboard_embed(bot)
    if msg:
        await msg.edit(embed=e)
    elif create:
        msg = await ch.send(embed=e)
        await bot.db.set_setting('workshop_leaderboard_message_id', msg.id)
    return True, 'تم تحديث لوحة أكثر المتفاعلين.'


async def refresh_all(bot, guild, create=False):
    ok, text = await refresh_panel(bot, guild, create)
    if not ok:
        return ok, text
    ok2, text2 = await refresh_leaderboard(bot, guild, create)
    if not ok2:
        return ok2, text2
    return True, 'تم نشر/تحديث لوحة الورش ولوحة أكثر المتفاعلين.'


async def _delete_message(message):
    try:
        await message.delete()
    except discord.HTTPException:
        pass


async def _wait_image(bot, interaction, timeout=90):
    def check(message):
        return (
            message.author.id == interaction.user.id
            and message.channel.id == interaction.channel_id
            and any(image_attachment(a) for a in message.attachments)
        )

    message = await bot.wait_for('message', timeout=timeout, check=check)
    attachment = next(a for a in message.attachments if image_attachment(a))
    raw = await attachment.read()
    filename = attachment.filename or f'{interaction.user.id}.png'
    return message, raw, filename


async def _send_log(bot, guild, member, service, modification_type, files_data):
    log_id = int(await bot.db.get_setting('workshop_log_channel_id', '0') or 0)
    log_ch = guild.get_channel(log_id)
    if not isinstance(log_ch, discord.TextChannel):
        return False

    e = discord.Embed(title='🛠️ سجل خدمة ورشة', timestamp=datetime.now(timezone.utc))
    e.add_field(name='الموظف', value=f'{member.mention}\n`{member.id}`', inline=True)
    e.add_field(name='الخدمة', value=service, inline=True)
    if modification_type:
        e.add_field(name='نوع التعديل', value=modification_type, inline=True)
    if files_data:
        labels = [x[0] for x in files_data]
        e.add_field(name='المرفقات', value='\n'.join(f'• {x}' for x in labels), inline=False)

    discord_files = [discord.File(io.BytesIO(raw), filename=filename) for _, raw, filename in files_data]
    await log_ch.send(embed=e, files=discord_files)
    return True


async def collect_service(bot, interaction, service, modification_type=''):
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        return

    log_id = int(await bot.db.get_setting('workshop_log_channel_id', '0') or 0)
    if not isinstance(interaction.guild.get_channel(log_id), discord.TextChannel):
        if interaction.response.is_done():
            await interaction.followup.send('⚠️ روم لوق الورش غير محدد.', ephemeral=True)
        else:
            await interaction.response.send_message('⚠️ روم لوق الورش غير محدد.', ephemeral=True)
        return

    key = ('workshop', interaction.guild.id, interaction.user.id)
    if key in bot.pending_scans:
        if interaction.response.is_done():
            await interaction.followup.send('لديك تسجيل ورشة قيد الانتظار.', ephemeral=True)
        else:
            await interaction.response.send_message('لديك تسجيل ورشة قيد الانتظار.', ephemeral=True)
        return

    bot.pending_scans.add(key)
    try:
        if not interaction.response.is_done():
            await interaction.response.edit_message(content='📸 أرسل **صورة الفاتورة** في نفس الروم خلال 90 ثانية.', embed=None, view=None)
        else:
            await interaction.followup.send('📸 أرسل **صورة الفاتورة** في نفس الروم خلال 90 ثانية.', ephemeral=True)

        invoice_message, invoice_raw, invoice_name = await _wait_image(bot, interaction)
        await _delete_message(invoice_message)
        files_data = [('صورة الفاتورة', invoice_raw, f'invoice-{invoice_name}')]
        car_name = ''

        if service == 'تعديل مركبة':
            await interaction.followup.send('✅ استلمت الفاتورة. الآن أرسل **صورة السيارة** في نفس الروم خلال 90 ثانية.', ephemeral=True)
            car_message, car_raw, car_name = await _wait_image(bot, interaction)
            await _delete_message(car_message)
            files_data.append(('صورة السيارة', car_raw, f'car-{car_name}'))

        logged = await _send_log(bot, interaction.guild, interaction.user, service, modification_type, files_data)
        if not logged:
            await interaction.followup.send('⚠️ تعذر الوصول إلى روم اللوق ولم يتم اعتماد العملية.', ephemeral=True)
            return

        await bot.db.add_workshop_entry(
            interaction.user.id,
            service,
            modification_type,
            invoice_name,
            car_name,
        )
        await refresh_leaderboard(bot, interaction.guild, create=True)
        await interaction.followup.send('✅ تم تسجيل خدمة الورشة واعتمادها وتحديث لوحة أكثر المتفاعلين.', ephemeral=True)
    except asyncio.TimeoutError:
        await interaction.followup.send('⌛ انتهى الوقت ولم يتم تسجيل الخدمة.', ephemeral=True)
    except Exception as exc:
        print('workshop error', repr(exc))
        await interaction.followup.send('حدث خطأ أثناء تسجيل خدمة الورشة.', ephemeral=True)
    finally:
        bot.pending_scans.discard(key)


class ModificationTypeSelect(discord.ui.Select):
    def __init__(self, bot):
        self.bot = bot
        super().__init__(
            placeholder='حدد نوع تعديل المركبة — مطلوب',
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(label='Full Stage', value='Full Stage', emoji='🏁'),
                discord.SelectOption(label='أخرى', value='أخرى', emoji='🔧'),
            ],
        )

    async def callback(self, i):
        await collect_service(self.bot, i, 'تعديل مركبة', self.values[0])


class ModificationTypeView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=120)
        self.add_item(ModificationTypeSelect(bot))


class ServiceSelect(discord.ui.Select):
    def __init__(self, bot):
        self.bot = bot
        super().__init__(
            placeholder='وش الخدمة اللي بعتها؟',
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(label='تعديل مركبة', value='vehicle_mod', emoji='🚗', description='يتطلب صورة الفاتورة وصورة السيارة'),
                discord.SelectOption(label='بيع عدة تصليح', value='repair_kit', emoji='🧰', description='يتطلب صورة الفاتورة'),
            ],
        )

    async def callback(self, i):
        if self.values[0] == 'vehicle_mod':
            await i.response.edit_message(content='حدد نوع تعديل المركبة أولًا:', embed=None, view=ModificationTypeView(self.bot))
            return
        await collect_service(self.bot, i, 'بيع عدة تصليح')


class ServiceSelectView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=120)
        self.add_item(ServiceSelect(bot))


class WorkshopPanelView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label='تسجيل خدمة', emoji='🛠️', style=discord.ButtonStyle.primary, custom_id='workshop:register:v1')
    async def register(self, i, b):
        if not i.guild or not isinstance(i.user, discord.Member):
            await i.response.send_message('استخدم الزر داخل السيرفر.', ephemeral=True)
            return
        await i.response.send_message('اختر الخدمة التي قمت ببيعها:', view=ServiceSelectView(self.bot), ephemeral=True)
