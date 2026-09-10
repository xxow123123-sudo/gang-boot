# -*- coding: utf-8 -*-
import asyncio
from datetime import datetime, timezone

import discord

import events
from db import RESOURCE_NAMES

RESOURCE_LABELS = events.RESOURCE_LABELS


def stock_embed(label, stock, description=''):
    e = discord.Embed(title=f'📦 {label}', description=description or None)
    for key in RESOURCE_NAMES:
        e.add_field(name=RESOURCE_LABELS[key], value=f"**{int(stock.get(key, 0) or 0):,}**", inline=True)
    return e


async def panel_embed(bot):
    title = await bot.db.get_setting('warehouse_panel_title', '📦 حالة المخازن')
    description = await bot.db.get_setting(
        'warehouse_panel_description',
        'اختر المستودع من الأزرار بالأسفل ثم أرسل صورة الموارد لتحديث بياناته.'
    )
    e = discord.Embed(title=title[:256], description=description[:1500])
    image = (await bot.db.get_setting('warehouse_panel_image_url', '')).strip()
    if image.startswith(('http://', 'https://')):
        e.set_image(url=image)

    rows = await bot.db.warehouse_locations(enabled_only=True)
    if not rows:
        e.add_field(name='لا توجد مستودعات', value='أضف مستودعًا من `/settings` ثم انشر اللوحة.', inline=False)
    else:
        for row in rows:
            stock = await bot.db.warehouse_stock(row['warehouse_id'])
            values = '\n'.join(
                f"**{RESOURCE_LABELS[key]}:** {int(stock.get(key, 0) or 0):,}"
                for key in RESOURCE_NAMES
            )
            # Important: no total is displayed by design.
            e.add_field(name=f"📦 {row['label']}", value=values, inline=True)
    e.set_footer(text='كل صورة جديدة تستبدل بيانات المستودع السابقة بالكامل.')
    return e


async def panel_view(bot):
    rows = await bot.db.warehouse_locations(enabled_only=True)
    return WarehousePanelView(bot, rows) if rows else None


async def refresh_panel(bot, guild, create=False):
    cid = int(await bot.db.get_setting('warehouse_panel_channel_id', '0') or 0)
    ch = guild.get_channel(cid)
    if not isinstance(ch, discord.TextChannel):
        return False, 'حدد روم لوحة المخازن أولًا.'

    mid = int(await bot.db.get_setting('warehouse_panel_message_id', '0') or 0)
    msg = None
    if mid:
        try:
            msg = await ch.fetch_message(mid)
        except discord.HTTPException:
            pass

    e = await panel_embed(bot)
    v = await panel_view(bot)
    if msg:
        await msg.edit(embed=e, view=v)
    elif create:
        msg = await ch.send(embed=e, view=v)
        await bot.db.set_setting('warehouse_panel_message_id', msg.id)
    return True, 'تم تحديث لوحة المخازن.'


class WarehousePanelView(discord.ui.View):
    def __init__(self, bot, warehouses):
        super().__init__(timeout=None)
        self.bot = bot
        for index, warehouse in enumerate(warehouses[:20]):
            wid = warehouse['warehouse_id']
            button = discord.ui.Button(
                label=warehouse['label'][:80],
                emoji='📦',
                style=discord.ButtonStyle.primary,
                custom_id=f'warehouse:update:{wid}',
                row=index // 5,
            )

            async def callback(interaction, warehouse_id=wid):
                await self.update_warehouse(interaction, warehouse_id)

            button.callback = callback
            self.add_item(button)

    async def update_warehouse(self, i: discord.Interaction, warehouse_id: str):
        if not i.guild or not isinstance(i.user, discord.Member):
            await i.response.send_message('استخدم هذا الزر داخل السيرفر.', ephemeral=True)
            return

        warehouse = await self.bot.db.warehouse_location(warehouse_id)
        if not warehouse or not int(warehouse.get('enabled', 1)):
            await i.response.send_message('هذا المستودع غير متاح حاليًا.', ephemeral=True)
            return

        key = ('warehouse', i.guild.id, i.user.id)
        if key in self.bot.pending_scans:
            await i.response.send_message('لديك قراءة صورة قيد الانتظار.', ephemeral=True)
            return

        self.bot.pending_scans.add(key)
        await i.response.send_message(
            f"📸 أرسل صورة موارد **{warehouse['label']}** في نفس الروم خلال 90 ثانية.\n"
            'سيتم **استبدال** القيم السابقة بالكامل بقيم الصورة الجديدة.',
            ephemeral=True,
        )

        def check(message):
            return (
                message.author.id == i.user.id
                and message.channel.id == i.channel_id
                and any(events.image_attachment(a) for a in message.attachments)
            )

        try:
            message = await self.bot.wait_for('message', timeout=90, check=check)
            attachment = next(a for a in message.attachments if events.image_attachment(a))
            raw = await attachment.read()

            try:
                resources = await events.read_resources(
                    self.bot.openai_client,
                    self.bot.openai_model,
                    raw,
                    attachment.content_type or 'image/jpeg',
                )
            except ValueError:
                await i.followup.send('⚠️ لم أستطع قراءة جميع قيم Owned بوضوح. لم يتم تغيير المستودع.', ephemeral=True)
                return

            await self.bot.db.replace_warehouse_stock(warehouse_id, resources, i.user.id)

            # Keep the public channel clean when the bot has permission, but do not
            # block the update if it cannot delete the uploaded image.
            try:
                await message.delete()
            except discord.HTTPException:
                pass

            await refresh_panel(self.bot, i.guild, create=True)
            await i.followup.send(
                embed=stock_embed(
                    warehouse['label'],
                    resources,
                    '✅ تم تحديث المستودع. القيم الجديدة استبدلت القيم السابقة بالكامل.',
                ),
                ephemeral=True,
            )
        except asyncio.TimeoutError:
            await i.followup.send('⌛ انتهى الوقت ولم يتم تغيير بيانات المستودع.', ephemeral=True)
        except Exception as exc:
            print('warehouse scan error', repr(exc))
            await i.followup.send('حدث خطأ أثناء قراءة صورة المستودع، ولم يتم تغيير البيانات.', ephemeral=True)
        finally:
            self.bot.pending_scans.discard(key)
