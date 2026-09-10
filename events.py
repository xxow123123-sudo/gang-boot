# -*- coding: utf-8 -*-
import asyncio, base64, hashlib, io, json, re
from datetime import datetime, timezone
from typing import Optional
import discord
from db import RESOURCE_NAMES, total_for

RESOURCE_LABELS={"steel":"Steel","aluminum":"Aluminum","rubber":"Rubber","metalscrap":"Metalscrap","iron":"Iron","plastic":"Plastic","copper":"Copper","glass":"Glass"}
VISION_INSTRUCTIONS='''You are reading a game inventory screenshot for a Discord resource event.
There are exactly eight resource cards: Steel, Aluminum, Rubber, Metalscrap, Iron, Plastic, Copper, Glass.
For EACH resource, read ONLY the integer shown after the label "Owned:".
Never use Capacity. Never infer missing values. If unreadable, return null.
Return ONLY a JSON object with exactly these lowercase keys:
steel, aluminum, rubber, metalscrap, iron, plastic, copper, glass
Every value must be a non-negative integer or null.'''


def resources_total(r): return sum(int(r[k]) for k in RESOURCE_NAMES)

def image_attachment(a):
    if a.content_type and a.content_type.startswith("image/"): return True
    suffix=a.filename.lower().rsplit('.',1)[-1] if '.' in a.filename else ''
    return suffix in {'png','jpg','jpeg','webp'}

async def read_resources(client,model,image_bytes,mime):
    data_url=f"data:{mime};base64,{base64.b64encode(image_bytes).decode('ascii')}"
    resp=await client.responses.create(model=model,instructions=VISION_INSTRUCTIONS,input=[{"role":"user","content":[{"type":"input_text","text":"Read Owned values and return the required JSON."},{"type":"input_image","image_url":data_url,"detail":"high"}]}],max_output_tokens=300)
    raw=(resp.output_text or '').strip()
    if raw.startswith('```'):
        raw=re.sub(r'^```(?:json)?\s*','',raw,flags=re.I); raw=re.sub(r'\s*```$','',raw)
    try: data=json.loads(raw)
    except json.JSONDecodeError:
        m=re.search(r'\{.*\}',raw,flags=re.S)
        if not m: raise ValueError('bad json')
        data=json.loads(m.group(0))
    out={}
    for k in RESOURCE_NAMES:
        v=data.get(k)
        if v is None or isinstance(v,bool): raise ValueError(k)
        if isinstance(v,str):
            v=v.replace(',','').strip()
            if not v.isdigit(): raise ValueError(k)
            v=int(v)
        if not isinstance(v,int) or v<0: raise ValueError(k)
        out[k]=v
    return out


def points_embed(member,row):
    e=discord.Embed(title='📊 مواردك الحالية',description=f'الحساب: {member.mention}')
    for k in RESOURCE_NAMES: e.add_field(name=RESOURCE_LABELS[k],value=f"**{int(row.get(k,0) or 0):,}**",inline=True)
    adj=int(row.get('admin_adjustment',0) or 0)
    if adj: e.add_field(name='إضافة/خصم إداري',value=f'**{adj:+,}**',inline=True)
    e.add_field(name='📦 المجموع الكلي',value=f'**{total_for(row):,}**',inline=False)
    return e

def scan_embed(res,desc='راجع الأرقام قبل الاعتماد.'):
    e=discord.Embed(title='🔎 نتيجة قراءة الصورة',description=desc)
    for k in RESOURCE_NAMES: e.add_field(name=RESOURCE_LABELS[k],value=f'**{res[k]:,}**',inline=True)
    e.add_field(name='📦 مجموع هذه الصورة',value=f'**{resources_total(res):,}**',inline=False); return e

def log_embed(member,channel,status,res=None,note=None):
    e=discord.Embed(title='🧾 لوق صورة موارد',description=status,timestamp=datetime.now(timezone.utc)); e.add_field(name='العضو',value=f'{member.mention}\n`{member.id}`',inline=True); e.add_field(name='الروم الأصلي',value=channel.mention,inline=True)
    if res:
        e.add_field(name='الموارد المقروءة',value='\n'.join(f'**{RESOURCE_LABELS[k]}:** {res[k]:,}' for k in RESOURCE_NAMES),inline=False); e.add_field(name='مجموع الصورة',value=f'**{resources_total(res):,}**',inline=False)
    if note: e.add_field(name='ملاحظة',value=note,inline=False)
    return e

async def safe_edit_log(msg,member,channel,status,res=None,note=None):
    if not msg:return
    try: await msg.edit(embed=log_embed(member,channel,status,res,note))
    except discord.HTTPException: pass

async def panel_embed(bot):
    name=await bot.db.get_setting('event_name','فعالية جمع الموارد'); desc=await bot.db.get_setting('event_description',''); active=await bot.db.is_active(); e=discord.Embed(title=f'🏆 {name}',description=desc)
    image=(await bot.db.get_setting('event_image_url','')).strip()
    if image.startswith(('http://','https://')): e.set_image(url=image)
    e.add_field(name='طريقة المشاركة',value='1. اضغط **دخول الفعالية** واقرأ الشروط.\n2. وافق على الشروط.\n3. استخدم **حساب الموارد** وارفع الصورة.',inline=False); e.set_footer(text='الفعالية مفعلة الآن.' if active else 'الفعالية غير مفعلة حاليًا.'); return e

async def panel_view(bot):
    labels={"join":await bot.db.get_setting('event_join_label','دخول الفعالية'),"scan":await bot.db.get_setting('event_scan_label','حساب الموارد'),"points":await bot.db.get_setting('event_points_label','نقاطي'),"leaderboard":await bot.db.get_setting('event_leaderboard_label','الترتيب')}
    return EventPanelView(bot,labels)

async def refresh_leaderboard(bot,guild,create=False):
    cid=int(await bot.db.get_setting('event_leaderboard_channel_id','0') or 0); ch=guild.get_channel(cid)
    if not isinstance(ch,discord.TextChannel): return False,'حدد روم لوحة المتصدرين.'
    rows=await bot.db.get_balances(); name=await bot.db.get_setting('event_name','الفعالية'); medals=['🥇','🥈','🥉']; lines=[]
    for i,r in enumerate(rows[:25]): lines.append(f"{medals[i] if i<3 else f'**{i+1}.**'} <@{r['user_id']}> — **{total_for(r):,}**")
    e=discord.Embed(title=f'🏆 المتصدرون — {name}',description='\n'.join(lines) if lines else 'لا توجد نقاط مسجلة حاليًا.'); e.set_footer(text='تتحدث تلقائيًا بعد كل صورة معتمدة أو تعديل إداري.')
    mid=int(await bot.db.get_setting('event_leaderboard_message_id','0') or 0); msg=None
    if mid:
        try: msg=await ch.fetch_message(mid)
        except discord.HTTPException: pass
    if msg: await msg.edit(embed=e)
    elif create:
        msg=await ch.send(embed=e); await bot.db.set_setting('event_leaderboard_message_id',msg.id)
    return True,'تم تحديث لوحة المتصدرين.'

async def publish(bot,guild):
    cid=int(await bot.db.get_setting('event_panel_channel_id','0') or 0); ch=guild.get_channel(cid)
    if not isinstance(ch,discord.TextChannel): return False,'حدد روم لوحة الفعالية أولًا.'
    mid=int(await bot.db.get_setting('event_panel_message_id','0') or 0); msg=None
    if mid:
        try: msg=await ch.fetch_message(mid)
        except discord.HTTPException: pass
    e=await panel_embed(bot); v=await panel_view(bot)
    if msg: await msg.edit(embed=e,view=v)
    else:
        msg=await ch.send(embed=e,view=v); await bot.db.set_setting('event_panel_message_id',msg.id)
    ok,text=await refresh_leaderboard(bot,guild,create=True)
    return (ok,'تم تحديث لوحات الفعالية.' if ok else text)

class TermsView(discord.ui.View):
    def __init__(self,bot,eid,uid): super().__init__(timeout=300); self.bot=bot; self.eid=eid; self.uid=uid
    async def interaction_check(self,i):
        if i.user.id!=self.uid: await i.response.send_message('هذه الموافقة تخص صاحب الطلب فقط.',ephemeral=True); return False
        return True
    @discord.ui.button(label='موافق على الشروط',emoji='✅',style=discord.ButtonStyle.success)
    async def agree(self,i,b):
        if not await self.bot.db.is_active() or await self.bot.db.current_event_id()!=self.eid: await i.response.edit_message(content='انتهت أو تغيرت الفعالية.',embed=None,view=None); return
        await self.bot.db.accept_terms(self.eid,self.uid); await i.response.edit_message(content='✅ تم تسجيلك في الفعالية. يمكنك الآن استخدام حساب الموارد.',embed=None,view=None)
    @discord.ui.button(label='إلغاء',style=discord.ButtonStyle.secondary)
    async def cancel(self,i,b): await i.response.edit_message(content='تم إلغاء الدخول.',embed=None,view=None)

class ConfirmView(discord.ui.View):
    def __init__(self,bot,uid,eid,h,res,logmsg,member,channel): super().__init__(timeout=120); self.bot=bot; self.uid=uid; self.eid=eid; self.h=h; self.res=res; self.logmsg=logmsg; self.member=member; self.channel=channel; self.done=False
    async def interaction_check(self,i):
        if i.user.id!=self.uid: await i.response.send_message('هذه الأزرار تخص صاحب الصورة.',ephemeral=True); return False
        return True
    @discord.ui.button(label='اعتماد',emoji='✅',style=discord.ButtonStyle.success)
    async def confirm(self,i,b):
        if self.done: await i.response.send_message('تم التعامل مع الصورة.',ephemeral=True); return
        ok,reason=await self.bot.db.add_submission(self.eid,self.uid,self.h,self.res); self.done=True
        for x in self.children:x.disabled=True
        if not ok:
            text={'duplicate':'⚠️ الصورة مكررة.','event_changed':'⚠️ تغيرت الفعالية.','inactive':'🔒 انتهت الفعالية.'}.get(reason,'تعذر الاعتماد.'); await safe_edit_log(self.logmsg,self.member,self.channel,'⚠️ لم تعتمد',self.res,text); await i.response.edit_message(embed=scan_embed(self.res,text),view=self); return
        bal=await self.bot.db.get_balance(self.uid); await safe_edit_log(self.logmsg,self.member,self.channel,'✅ تم اعتماد الصورة',self.res,f'الرصيد بعد الاعتماد: {total_for(bal):,}'); await i.response.edit_message(embed=scan_embed(self.res,f'✅ تمت إضافة **{resources_total(self.res):,}**.\nرصيدك: **{total_for(bal):,}**'),view=self)
        if i.guild: await refresh_leaderboard(self.bot,i.guild,create=True)
    @discord.ui.button(label='إلغاء',emoji='❌',style=discord.ButtonStyle.danger)
    async def cancel(self,i,b):
        self.done=True
        for x in self.children:x.disabled=True
        await safe_edit_log(self.logmsg,self.member,self.channel,'❌ ألغى العضو الصورة',self.res); await i.response.edit_message(embed=scan_embed(self.res,'❌ تم الإلغاء ولم تضف موارد.'),view=self)

class EventPanelView(discord.ui.View):
    def __init__(self,bot,labels=None):
        super().__init__(timeout=None); self.bot=bot; labels=labels or {'join':'دخول الفعالية','scan':'حساب الموارد','points':'نقاطي','leaderboard':'الترتيب'}
        items=[('join','✅',discord.ButtonStyle.success,'event:join:v4',self.join),('scan','📸',discord.ButtonStyle.primary,'event:scan:v4',self.scan),('points','👤',discord.ButtonStyle.secondary,'event:points:v4',self.points),('leaderboard','🏆',discord.ButtonStyle.secondary,'event:board:v4',self.board)]
        for key,emoji,style,cid,cb in items:
            x=discord.ui.Button(label=labels[key][:80],emoji=emoji,style=style,custom_id=cid); x.callback=cb; self.add_item(x)
    async def join(self,i):
        if not i.guild or not isinstance(i.user,discord.Member): await i.response.send_message('استخدمه داخل السيرفر.',ephemeral=True); return
        if not await self.bot.db.is_active(): await i.response.send_message('🔒 لا توجد فعالية نشطة.',ephemeral=True); return
        eid=await self.bot.db.current_event_id()
        if await self.bot.db.is_participant(eid,i.user.id): await i.response.send_message('✅ أنت مسجل بالفعل.',ephemeral=True); return
        terms=await self.bot.db.get_setting('event_terms','لا توجد شروط.'); name=await self.bot.db.get_setting('event_name','الفعالية'); e=discord.Embed(title=f'📜 شروط {name}',description=terms[:4000]); e.set_footer(text='لن تسجل إلا بعد الضغط على موافق.'); await i.response.send_message(embed=e,view=TermsView(self.bot,eid,i.user.id),ephemeral=True)
    async def scan(self,i):
        if not i.guild or not isinstance(i.user,discord.Member): await i.response.send_message('استخدمه داخل السيرفر.',ephemeral=True); return
        if not await self.bot.db.is_active(): await i.response.send_message('🔒 لا توجد فعالية نشطة.',ephemeral=True); return
        eid=await self.bot.db.current_event_id()
        if not await self.bot.db.is_participant(eid,i.user.id): await i.response.send_message('⚠️ اضغط دخول الفعالية ووافق على الشروط أولًا.',ephemeral=True); return
        logid=int(await self.bot.db.get_setting('log_channel_id','0') or 0); logch=i.guild.get_channel(logid); ch=i.channel; me=i.guild.me
        if not isinstance(logch,discord.TextChannel): await i.response.send_message('⚠️ روم اللوق غير محدد.',ephemeral=True); return
        if not isinstance(ch,discord.TextChannel) or not me: await i.response.send_message('تعذر التحقق من الروم.',ephemeral=True); return
        if not ch.permissions_for(me).manage_messages: await i.response.send_message('⚠️ يحتاج البوت Manage Messages في روم المشاركة.',ephemeral=True); return
        key=(i.guild.id,i.user.id)
        if key in self.bot.pending_scans: await i.response.send_message('لديك قراءة صورة قيد الانتظار.',ephemeral=True); return
        self.bot.pending_scans.add(key); await i.response.send_message('📸 أرسل صورة الموارد في **نفس الروم** خلال 90 ثانية.',ephemeral=True)
        def check(m): return m.author.id==i.user.id and m.channel.id==i.channel_id and any(image_attachment(a) for a in m.attachments)
        try:
            m=await self.bot.wait_for('message',timeout=90,check=check); a=next(x for x in m.attachments if image_attachment(x)); raw=await a.read(); h=hashlib.sha256(raw).hexdigest(); eid=await self.bot.db.current_event_id(); lf=discord.File(io.BytesIO(raw),filename=a.filename or f'{i.user.id}.png'); lm=await logch.send(embed=log_embed(i.user,ch,'⏳ جاري قراءة الصورة'),file=lf)
            try: await m.delete()
            except discord.HTTPException: await i.followup.send('⚠️ تعذر حذف الصورة من الروم.',ephemeral=True); return
            if await self.bot.db.is_duplicate(eid,h): await safe_edit_log(lm,i.user,ch,'⚠️ صورة مكررة'); await i.followup.send('⚠️ هذه الصورة معتمدة مسبقًا.',ephemeral=True); return
            try: res=await read_resources(self.bot.openai_client,self.bot.openai_model,raw,a.content_type or 'image/jpeg')
            except ValueError: await safe_edit_log(lm,i.user,ch,'⚠️ تعذر قراءة الصورة'); await i.followup.send('⚠️ لم أستطع قراءة جميع Owned بوضوح.',ephemeral=True); return
            await safe_edit_log(lm,i.user,ch,'🕐 بانتظار اعتماد العضو',res); await i.followup.send(embed=scan_embed(res),view=ConfirmView(self.bot,i.user.id,eid,h,res,lm,i.user,ch),ephemeral=True)
        except asyncio.TimeoutError: await i.followup.send('⌛ انتهى الوقت.',ephemeral=True)
        except Exception as exc: print('scan error',repr(exc)); await i.followup.send('حدث خطأ أثناء قراءة الصورة.',ephemeral=True)
        finally: self.bot.pending_scans.discard(key)
    async def points(self,i): await i.response.send_message(embed=points_embed(i.user,await self.bot.db.get_balance(i.user.id)),ephemeral=True)
    async def board(self,i):
        rows=await self.bot.db.get_balances()
        if not rows: await i.response.send_message('لا توجد نقاط حتى الآن.',ephemeral=True); return
        medals=['🥇','🥈','🥉']; lines=[f"{medals[x] if x<3 else f'**{x+1}.**'} <@{r['user_id']}> — **{total_for(r):,}**" for x,r in enumerate(rows[:20])]; await i.response.send_message(embed=discord.Embed(title='🏆 ترتيب الفعالية',description='\n'.join(lines)),ephemeral=True)

class EndEventView(discord.ui.View):
    def __init__(self,bot,uid): super().__init__(timeout=120); self.bot=bot; self.uid=uid
    async def interaction_check(self,i):
        if i.user.id!=self.uid: await i.response.send_message('التأكيد للإداري الذي طلبه.',ephemeral=True); return False
        return True
    @discord.ui.button(label='نعم، إنهاء وتصفير',emoji='✅',style=discord.ButtonStyle.danger)
    async def finish(self,i,b):
        result=await self.bot.db.end_event()
        if not result: await i.response.edit_message(content='الفعالية منتهية.',embed=None,view=None); return
        eid,rows=result; rows.sort(key=total_for,reverse=True); medals=['🥇','🥈','🥉']; lines=[f"{medals[x] if x<3 else f'**{x+1}.**'} <@{r['user_id']}> — **{total_for(r):,}**" for x,r in enumerate(rows[:10])]; e=discord.Embed(title=f'🏁 النتائج النهائية — #{eid}',description='\n'.join(lines) if lines else 'لا توجد مشاركات.'); e.set_footer(text='تم حفظ النتائج وتصفير اللوحة الثابتة.'); await i.response.edit_message(content='✅ انتهت الفعالية وتم التصفير.',embed=e,view=None)
        if i.guild: await refresh_leaderboard(self.bot,i.guild,create=True); await publish(self.bot,i.guild)
    @discord.ui.button(label='إلغاء',style=discord.ButtonStyle.secondary)
    async def cancel(self,i,b): await i.response.edit_message(content='تم الإلغاء.',embed=None,view=None)
