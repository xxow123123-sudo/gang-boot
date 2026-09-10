# -*- coding: utf-8 -*-
import asyncio, json, re
from datetime import datetime, timezone
import discord


def parse_ids(raw):
    try:
        data=json.loads(raw or '[]'); return [int(x) for x in data]
    except Exception:return []

def safe_name(s):
    s=re.sub(r'[^\w\-]+','-',s.strip().lower(),flags=re.UNICODE); s=re.sub(r'-+','-',s).strip('-'); return s[:70] or 'ticket'

async def panel_embed(bot):
    e=discord.Embed(title=await bot.db.get_setting('ticket_panel_title','🎫 التذاكر'),description=await bot.db.get_setting('ticket_panel_description','اختر نوع التذكرة من الأزرار بالأسفل.'))
    image=(await bot.db.get_setting('ticket_panel_image_url','')).strip()
    if image.startswith(('http://','https://')):e.set_image(url=image)
    return e

async def refresh_panel(bot,guild,create=False):
    cid=int(await bot.db.get_setting('ticket_panel_channel_id','0') or 0); ch=guild.get_channel(cid)
    if not isinstance(ch,discord.TextChannel):return False,'حدد روم لوحة التذاكر.'
    types=await bot.db.ticket_types(True); mid=int(await bot.db.get_setting('ticket_panel_message_id','0') or 0); msg=None
    if mid:
        try:msg=await ch.fetch_message(mid)
        except discord.HTTPException:pass
    if msg: await msg.edit(embed=await panel_embed(bot),view=TicketPanelView(bot,types))
    elif create:
        msg=await ch.send(embed=await panel_embed(bot),view=TicketPanelView(bot,types)); await bot.db.set_setting('ticket_panel_message_id',msg.id)
    return True,'تم تحديث لوحة التذاكر.'

async def create_ticket(bot,interaction,type_data,answers):
    if not interaction.guild or not isinstance(interaction.user,discord.Member): await interaction.followup.send('تعذر إنشاء التذكرة.',ephemeral=True);return
    old=await bot.db.open_ticket(interaction.guild.id,interaction.user.id,type_data['type_id'])
    if old:
        ch=interaction.guild.get_channel(int(old['channel_id']))
        if ch: await interaction.followup.send(f'لديك تذكرة مفتوحة: {ch.mention}',ephemeral=True);return
    cat=interaction.guild.get_channel(int(type_data.get('category_id',0) or 0))
    if not isinstance(cat,discord.CategoryChannel): await interaction.followup.send('⚠️ لم يتم تحديد Category لهذا النوع.',ephemeral=True);return
    overwrites={interaction.guild.default_role:discord.PermissionOverwrite(view_channel=False),interaction.user:discord.PermissionOverwrite(view_channel=True,send_messages=True,read_message_history=True,attach_files=True)}
    if interaction.guild.me:overwrites[interaction.guild.me]=discord.PermissionOverwrite(view_channel=True,send_messages=True,manage_channels=True,manage_messages=True,read_message_history=True)
    for rid in parse_ids(type_data.get('staff_role_ids','[]')):
        role=interaction.guild.get_role(rid)
        if role:overwrites[role]=discord.PermissionOverwrite(view_channel=True,send_messages=True,read_message_history=True,attach_files=True)
    ch=await interaction.guild.create_text_channel(name=f"{safe_name(type_data['label'])}-{safe_name(interaction.user.display_name)}"[:95],category=cat,overwrites=overwrites,reason='Ticket')
    await bot.db.create_ticket(interaction.guild.id,ch.id,interaction.user.id,type_data['type_id'],answers)
    e=discord.Embed(title=f"🎫 {type_data['label']}",description=type_data.get('welcome_message') or 'تم فتح التذكرة.',timestamp=datetime.now(timezone.utc));e.add_field(name='صاحب التذكرة',value=interaction.user.mention,inline=False)
    for q,a in answers.items(): e.add_field(name=q[:256],value=(a or '—')[:1024],inline=False)
    mentions=[interaction.user.mention]+[f'<@&{rid}>' for rid in parse_ids(type_data.get('staff_role_ids','[]'))]
    await ch.send(' '.join(mentions),embed=e,view=TicketCloseView(bot))
    logid=int(await bot.db.get_setting('ticket_log_channel_id','0') or 0);logch=interaction.guild.get_channel(logid)
    if isinstance(logch,discord.TextChannel):await logch.send(embed=discord.Embed(title='🎫 فتح تذكرة',description=f'{interaction.user.mention} فتح {ch.mention}\nالنوع: **{type_data["label"]}**',timestamp=datetime.now(timezone.utc)))
    await interaction.followup.send(f'✅ تم فتح تذكرتك: {ch.mention}',ephemeral=True)

class QuestionsModal(discord.ui.Modal):
    def __init__(self,bot,t,questions):
        super().__init__(title=f"{t['label']} — الأسئلة"[:45],timeout=600);self.bot=bot;self.t=t;self.q=questions[:5];self.fields=[]
        for q in self.q:
            x=discord.ui.TextInput(label=q[:45],style=discord.TextStyle.paragraph,max_length=1000);self.fields.append(x);self.add_item(x)
    async def on_submit(self,i):
        await i.response.defer(ephemeral=True,thinking=True);await create_ticket(self.bot,i,self.t,{q:f.value for q,f in zip(self.q,self.fields)})

class TicketTypeButton(discord.ui.Button):
    def __init__(self,bot,t,index):
        self.bot=bot;self.type_id=t['type_id']
        kwargs=dict(label=t['label'][:80],style=discord.ButtonStyle.primary,custom_id=f"tickets:open:{self.type_id}:v5",row=index//5)
        emoji=t.get('emoji') or None
        if emoji:kwargs['emoji']=emoji
        try:super().__init__(**kwargs)
        except Exception:
            kwargs.pop('emoji',None);super().__init__(**kwargs)
    async def callback(self,i):
        t=await self.bot.db.ticket_type(self.type_id)
        if not t or not int(t['enabled']):await i.response.send_message('هذا النوع غير متاح.',ephemeral=True);return
        try:q=[str(x).strip() for x in json.loads(t.get('questions','[]')) if str(x).strip()][:5]
        except Exception:q=[]
        if q:await i.response.send_modal(QuestionsModal(self.bot,t,q))
        else:await i.response.defer(ephemeral=True,thinking=True);await create_ticket(self.bot,i,t,{})

class TicketPanelView(discord.ui.View):
    def __init__(self,bot,types):
        super().__init__(timeout=None);self.bot=bot
        for index,t in enumerate(types[:25]):self.add_item(TicketTypeButton(bot,t,index))

class CloseConfirm(discord.ui.View):
    def __init__(self,bot,uid):super().__init__(timeout=60);self.bot=bot;self.uid=uid
    async def interaction_check(self,i):
        if i.user.id!=self.uid:await i.response.send_message('هذا التأكيد يخص صاحب الطلب.',ephemeral=True);return False
        return True
    @discord.ui.button(label='تأكيد الإغلاق',emoji='🔒',style=discord.ButtonStyle.danger)
    async def confirm(self,i,b):
        if not isinstance(i.channel,discord.TextChannel) or not i.guild:await i.response.send_message('تعذر الإغلاق.',ephemeral=True);return
        t=await self.bot.db.ticket_by_channel(i.channel.id)
        if not t or t['status']!='open':await i.response.send_message('التذكرة مغلقة أو غير مسجلة.',ephemeral=True);return
        await self.bot.db.close_ticket(i.channel.id,i.user.id);logid=int(await self.bot.db.get_setting('ticket_log_channel_id','0') or 0);logch=i.guild.get_channel(logid)
        if isinstance(logch,discord.TextChannel):await logch.send(embed=discord.Embed(title='🔒 إغلاق تذكرة',description=f'تم إغلاق **#{i.channel.name}** بواسطة {i.user.mention}',timestamp=datetime.now(timezone.utc)))
        await i.response.edit_message(content='✅ سيتم حذف التذكرة خلال 5 ثوانٍ.',embed=None,view=None);await asyncio.sleep(5)
        try:await i.channel.delete(reason='Ticket closed')
        except discord.HTTPException:pass
    @discord.ui.button(label='إلغاء',style=discord.ButtonStyle.secondary)
    async def cancel(self,i,b):await i.response.edit_message(content='تم إلغاء الإغلاق.',embed=None,view=None)

class TicketCloseView(discord.ui.View):
    def __init__(self,bot):super().__init__(timeout=None);self.bot=bot
    @discord.ui.button(label='إغلاق التذكرة',emoji='🔒',style=discord.ButtonStyle.danger,custom_id='tickets:close:v4')
    async def close(self,i,b):
        if not i.guild or not isinstance(i.user,discord.Member) or not isinstance(i.channel,discord.TextChannel):await i.response.send_message('تعذر الاستخدام.',ephemeral=True);return
        scoped=self.bot.for_guild(i.guild_id) if hasattr(self.bot,'for_guild') else self.bot
        ticket=await scoped.db.ticket_by_channel(i.channel.id)
        if not ticket:await i.response.send_message('هذه ليست تذكرة مسجلة.',ephemeral=True);return
        t=await scoped.db.ticket_type(ticket['type_id']);roles=parse_ids(t.get('staff_role_ids','[]')) if t else [];staff=any(r.id in roles for r in i.user.roles)
        if i.user.id!=int(ticket['user_id']) and not staff and not await scoped.is_global_admin(i.user):await i.response.send_message('ليس لديك صلاحية الإغلاق.',ephemeral=True);return
        await i.response.send_message('هل أنت متأكد من إغلاق التذكرة؟',view=CloseConfirm(scoped,i.user.id),ephemeral=True)
