# -*- coding: utf-8 -*-
import json
from datetime import datetime, timezone
import discord


def parse_ids(raw):
    try:return [int(x) for x in json.loads(raw or '[]')]
    except Exception:return []

def fmt(seconds):
    h,r=divmod(max(0,int(seconds or 0)),3600);m,_=divmod(r,60);return f'{h} س {m:02d} د'

async def panel_embed(bot):
    e=discord.Embed(title=await bot.db.get_setting('attendance_panel_title','🕒 تسجيل الدخول والخروج'),description=await bot.db.get_setting('attendance_panel_description',''))
    image=(await bot.db.get_setting('attendance_panel_image_url','')).strip()
    if image.startswith(('http://','https://')):e.set_image(url=image)
    return e

async def refresh_panel(bot,guild,create=False):
    cid=int(await bot.db.get_setting('attendance_panel_channel_id','0') or 0);ch=guild.get_channel(cid)
    if not isinstance(ch,discord.TextChannel):return False,'حدد روم لوحة الدخول والخروج.'
    mid=int(await bot.db.get_setting('attendance_panel_message_id','0') or 0);msg=None
    if mid:
        try:msg=await ch.fetch_message(mid)
        except discord.HTTPException:pass
    if msg:await msg.edit(embed=await panel_embed(bot),view=AttendancePanelView(bot))
    elif create:
        msg=await ch.send(embed=await panel_embed(bot),view=AttendancePanelView(bot));await bot.db.set_setting('attendance_panel_message_id',msg.id)
    return True,'تم تحديث لوحة الحضور.'

async def refresh_status(bot,guild,create=False):
    cid=int(await bot.db.get_setting('attendance_status_channel_id','0') or 0);ch=guild.get_channel(cid)
    if not isinstance(ch,discord.TextChannel):return False,'حدد روم حالة الموظفين.'
    sessions=await bot.db.sessions();active=[];sleep=[]
    for r in sessions:
        mention=f"<@{r['user_id']}>"
        (sleep if r['state']=='break' else active).append(mention)
    e=discord.Embed(title='📍 حالة الموظفين الحالية');e.add_field(name=f'🟢 مسجلون دخول ({len(active)})',value='\n'.join(active) if active else 'لا يوجد',inline=False);e.add_field(name=f'😴 غفوة ({len(sleep)})',value='\n'.join(sleep) if sleep else 'لا يوجد',inline=False);e.set_footer(text='تتحدث تلقائيًا عند الدخول والخروج والغفوة.')
    mid=int(await bot.db.get_setting('attendance_status_message_id','0') or 0);msg=None
    if mid:
        try:msg=await ch.fetch_message(mid)
        except discord.HTTPException:pass
    if msg:await msg.edit(embed=e)
    elif create:
        msg=await ch.send(embed=e);await bot.db.set_setting('attendance_status_message_id',msg.id)
    return True,'تم تحديث لوحة الحالة.'

async def refresh_staff(bot,guild,create=False):
    cid=int(await bot.db.get_setting('staff_board_channel_id','0') or 0);ch=guild.get_channel(cid)
    if not isinstance(ch,discord.TextChannel):return False,'حدد روم لوحة الموظفين.'
    roleids=set(parse_ids(await bot.db.get_setting('attendance_employee_role_ids','[]')));notes=await bot.db.notes();states={int(x['user_id']):x['state'] for x in await bot.db.sessions()};rows=[]
    members=[m for m in guild.members if not m.bot and roleids and any(r.id in roleids for r in m.roles)]
    for m in members:
        sec=await bot.db.total_seconds(m.id,True);state=' 🟢' if states.get(m.id)=='active' else (' 😴' if states.get(m.id)=='break' else '');line=f'• {m.mention}{state} — **{fmt(sec)}**'
        if notes.get(m.id):line+=f" — 📝 {notes[m.id]}"
        rows.append((sec,line))
    rows.sort(reverse=True,key=lambda x:x[0]);lines=[x[1] for x in rows];embeds=[]
    if not lines:embeds=[discord.Embed(title='👥 لوحة الموظفين',description='لا يوجد موظفون مطابقون للرتبة المحددة حاليًا.')]
    else:
        chunk=[];length=0;part=1
        for line in lines:
            if chunk and (len(chunk)>=25 or length+len(line)>3700):embeds.append(discord.Embed(title='👥 لوحة الموظفين' if part==1 else f'👥 لوحة الموظفين — {part}',description='\n'.join(chunk)));part+=1;chunk=[];length=0
            chunk.append(line);length+=len(line)+1
        if chunk:embeds.append(discord.Embed(title='👥 لوحة الموظفين' if part==1 else f'👥 لوحة الموظفين — {part}',description='\n'.join(chunk)))
        embeds=embeds[:10];embeds[-1].set_footer(text='الساعات تشمل الجلسة الحالية وتستثني الغفوة.')
    mid=int(await bot.db.get_setting('staff_board_message_id','0') or 0);msg=None
    if mid:
        try:msg=await ch.fetch_message(mid)
        except discord.HTTPException:pass
    if msg:await msg.edit(embeds=embeds)
    elif create:
        msg=await ch.send(embeds=embeds);await bot.db.set_setting('staff_board_message_id',msg.id)
    return True,'تم تحديث لوحة الموظفين.'

async def refresh_all(bot,guild,create=False):
    ok,text=await refresh_panel(bot,guild,create)
    if not ok:return ok,text
    await refresh_status(bot,guild,create);await refresh_staff(bot,guild,create);return True,'تم نشر/تحديث لوحات الحضور والموظفين.'

async def staff_log(bot,guild,embed):
    cid=int(await bot.db.get_setting('staff_log_channel_id','0') or 0);ch=guild.get_channel(cid)
    if isinstance(ch,discord.TextChannel):
        try:await ch.send(embed=embed)
        except discord.HTTPException:pass

class ForceSelect(discord.ui.UserSelect):
    def __init__(self,bot):super().__init__(placeholder='اختر الموظف لتسجيل خروجه إجباريًا');self.bot=bot
    async def callback(self,i):
        if not isinstance(i.user,discord.Member) or not await self.bot.is_attendance_admin(i.user):await i.response.send_message('⛔ للإدارة فقط.',ephemeral=True);return
        m=self.values[0];ok,worked=await self.bot.db.attendance_logout(m.id,i.user.id,True)
        if not ok:await i.response.send_message(f'{m.mention} غير مسجل دخول.',ephemeral=True);return
        await i.response.send_message(f'✅ تم تسجيل خروج {m.mention} إجباريًا. مدة الجلسة: **{fmt(worked)}**',ephemeral=True)
        if i.guild:await refresh_status(self.bot,i.guild,True);await refresh_staff(self.bot,i.guild,True);await staff_log(self.bot,i.guild,discord.Embed(title='⛔ خروج إجباري',description=f'{m.mention}\nبواسطة: {i.user.mention}\nالمدة: **{fmt(worked)}**',timestamp=datetime.now(timezone.utc)))
class ForceView(discord.ui.View):
    def __init__(self,bot):super().__init__(timeout=120);self.add_item(ForceSelect(bot))

class AttendancePanelView(discord.ui.View):
    def __init__(self,bot):super().__init__(timeout=None);self.bot=bot
    async def emp(self,i):
        if not isinstance(i.user,discord.Member) or not await self.bot.is_employee(i.user):await i.response.send_message('⛔ هذا الزر مخصص لرتبة الموظفين.',ephemeral=True);return False
        return True
    @discord.ui.button(label='دخول',emoji='🟢',style=discord.ButtonStyle.success,custom_id='attendance:login:v4')
    async def login(self,i,b):
        if not await self.emp(i):return
        ok,state=await self.bot.db.attendance_login(i.user.id)
        if not ok:await i.response.send_message('أنت مسجل دخول بالفعل.' if state=='active' else 'أنت في غفوة؛ اضغط غفوة للعودة.',ephemeral=True);return
        await i.response.send_message('✅ تم تسجيل دخولك وبدأ احتساب وقت المباشرة.',ephemeral=True)
        if i.guild:await refresh_status(self.bot,i.guild,True);await refresh_staff(self.bot,i.guild,True);await staff_log(self.bot,i.guild,discord.Embed(title='🟢 تسجيل دخول',description=i.user.mention,timestamp=datetime.now(timezone.utc)))
    @discord.ui.button(label='خروج',emoji='🔴',style=discord.ButtonStyle.danger,custom_id='attendance:logout:v4')
    async def logout(self,i,b):
        if not await self.emp(i):return
        ok,worked=await self.bot.db.attendance_logout(i.user.id,i.user.id,False)
        if not ok:await i.response.send_message('أنت غير مسجل دخول.',ephemeral=True);return
        total=await self.bot.db.total_seconds(i.user.id,False);await i.response.send_message(f'✅ تم تسجيل خروجك.\nمدة الجلسة: **{fmt(worked)}**\nإجمالي ساعاتك: **{fmt(total)}**',ephemeral=True)
        if i.guild:await refresh_status(self.bot,i.guild,True);await refresh_staff(self.bot,i.guild,True);await staff_log(self.bot,i.guild,discord.Embed(title='🔴 تسجيل خروج',description=f'{i.user.mention}\nمدة الجلسة: **{fmt(worked)}**',timestamp=datetime.now(timezone.utc)))
    @discord.ui.button(label='غفوة',emoji='😴',style=discord.ButtonStyle.secondary,custom_id='attendance:break:v4')
    async def sleep(self,i,b):
        if not await self.emp(i):return
        ok,state=await self.bot.db.attendance_break(i.user.id)
        if not ok:await i.response.send_message('سجل دخولك أولًا.',ephemeral=True);return
        await i.response.send_message('😴 بدأت الغفوة وتوقف احتساب الوقت مؤقتًا.' if state=='break' else '🟢 انتهت الغفوة وعاد احتساب الوقت.',ephemeral=True)
        if i.guild:await refresh_status(self.bot,i.guild,True);await refresh_staff(self.bot,i.guild,True)
    @discord.ui.button(label='خروج إجباري',emoji='⛔',style=discord.ButtonStyle.danger,custom_id='attendance:force:v4')
    async def force(self,i,b):
        if not isinstance(i.user,discord.Member) or not await self.bot.is_attendance_admin(i.user):await i.response.send_message('⛔ هذا الزر للإدارة فقط.',ephemeral=True);return
        await i.response.send_message('اختر الموظف:',view=ForceView(self.bot),ephemeral=True)
