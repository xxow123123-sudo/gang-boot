# -*- coding: utf-8 -*-
import json,re,secrets
import discord
import events,tickets,attendance,warehouses,workshops


def ids(raw):
    try:return [int(x) for x in json.loads(raw or '[]')]
    except Exception:return []
def dump(values):return json.dumps(sorted(set(int(x) for x in values)))
def good_url(s):return not s or s.startswith(('http://','https://'))

def home_embed():return discord.Embed(title='⚙️ لوحة إعدادات البوت',description='كل إعدادات البوت القابلة للتعديل موجودة هنا.\nاختر القسم من القائمة. هذه اللوحة **Ephemeral** ولا يراها إلا أنت.')

class HomeButton(discord.ui.Button):
    def __init__(self,bot,row=4):super().__init__(label='الرئيسية',emoji='🏠',style=discord.ButtonStyle.secondary,row=row);self.bot=bot
    async def callback(self,i):await i.response.edit_message(embed=home_embed(),view=SettingsHome(self.bot))

class SectionSelect(discord.ui.Select):
    def __init__(self,bot):
        self.bot=bot;super().__init__(placeholder='اختر قسم الإعدادات',options=[
            discord.SelectOption(label='إعدادات الفعاليات',value='events',emoji='🎉',description='الرسالة والشروط والأزرار والرومات'),
            discord.SelectOption(label='إعدادات التذاكر',value='tickets',emoji='🎫',description='اللوحة والأنواع والأسئلة والـ Category'),
            discord.SelectOption(label='إعدادات المخازن',value='warehouses',emoji='📦',description='المستودعات والأزرار ولوحة الموارد'),
            discord.SelectOption(label='نظام الورش',value='workshops',emoji='🛠️',description='لوحة الخدمات واللوق وأكثر المتفاعلين'),
            discord.SelectOption(label='الدخول والخروج',value='attendance',emoji='🕒',description='الرتب والرومات ونص اللوحة'),
            discord.SelectOption(label='الموظفون',value='staff',emoji='👥',description='لوحة الساعات والملاحظات'),
            discord.SelectOption(label='إعدادات عامة',value='general',emoji='⚙️',description='رتب إدارة البوت')])
    async def callback(self,i):
        v=self.values[0]
        if v=='events':await i.response.edit_message(embed=await event_embed(self.bot),view=EventSettings(self.bot))
        elif v=='tickets':await i.response.edit_message(embed=await ticket_embed(self.bot),view=TicketSettings(self.bot))
        elif v=='warehouses':await i.response.edit_message(embed=await warehouse_embed(self.bot,i.guild),view=WarehouseSettings(self.bot))
        elif v=='workshops':await i.response.edit_message(embed=await workshop_embed(self.bot,i.guild),view=WorkshopSettings(self.bot))
        elif v=='attendance':await i.response.edit_message(embed=await attendance_embed(self.bot),view=AttendanceSettings(self.bot))
        elif v=='staff':await i.response.edit_message(embed=staff_embed(),view=StaffSettings(self.bot))
        else:await i.response.edit_message(embed=await general_embed(self.bot,i.guild),view=GeneralSettings(self.bot))
class SettingsHome(discord.ui.View):
    def __init__(self,bot):super().__init__(timeout=900);self.add_item(SectionSelect(bot))

async def event_embed(bot):
    return discord.Embed(title='🎉 إعدادات الفعاليات',description=f"**الفعالية:** {await bot.db.get_setting('event_name')}\n**الحالة:** {'🟢 نشطة' if await bot.db.is_active() else '⚫ متوقفة'}\nمن هنا تتحكم بالرسالة والشروط والصورة وأسماء الأزرار والرومات.")
class EventModal(discord.ui.Modal,title='بيانات الفعالية'):
    def __init__(self,bot,name,desc,terms,image):
        super().__init__();self.bot=bot;self.name=discord.ui.TextInput(label='اسم الفعالية',default=name[:100],max_length=100);self.desc=discord.ui.TextInput(label='رسالة الفعالية',default=desc[:4000],style=discord.TextStyle.paragraph,max_length=4000);self.terms=discord.ui.TextInput(label='شروط الفعالية',default=terms[:4000],style=discord.TextStyle.paragraph,max_length=4000);self.image=discord.ui.TextInput(label='رابط صورة (اختياري)',default=image[:1000],required=False,max_length=1000)
        for x in(self.name,self.desc,self.terms,self.image):self.add_item(x)
    async def on_submit(self,i):
        if not good_url(self.image.value.strip()):await i.response.send_message('رابط الصورة غير صحيح.',ephemeral=True);return
        await self.bot.db.set_settings({'event_name':self.name.value.strip(),'event_description':self.desc.value.strip(),'event_terms':self.terms.value.strip(),'event_image_url':self.image.value.strip()})
        if i.guild:await events.publish(self.bot,i.guild)
        await i.response.edit_message(embed=await event_embed(self.bot),view=EventSettings(self.bot))
class EventButtonsModal(discord.ui.Modal,title='أسماء أزرار الفعالية'):
    def __init__(self,bot,v):
        super().__init__();self.bot=bot;self.a=discord.ui.TextInput(label='دخول الفعالية',default=v[0][:80]);self.b=discord.ui.TextInput(label='حساب الموارد',default=v[1][:80]);self.c=discord.ui.TextInput(label='نقاطي',default=v[2][:80]);self.d=discord.ui.TextInput(label='الترتيب',default=v[3][:80]);[self.add_item(x) for x in(self.a,self.b,self.c,self.d)]
    async def on_submit(self,i):
        await self.bot.db.set_settings({'event_join_label':self.a.value,'event_scan_label':self.b.value,'event_points_label':self.c.value,'event_leaderboard_label':self.d.value})
        if i.guild:await events.publish(self.bot,i.guild)
        await i.response.edit_message(embed=await event_embed(self.bot),view=EventSettings(self.bot))
class EChannel(discord.ui.ChannelSelect):
    def __init__(self,bot,key,placeholder,row):super().__init__(placeholder=placeholder,channel_types=[discord.ChannelType.text],row=row);self.bot=bot;self.key=key
    async def callback(self,i):await self.bot.db.set_setting(self.key,self.values[0].id);await i.response.send_message(f'✅ تم تحديد {self.values[0].mention}',ephemeral=True)
class EventSettings(discord.ui.View):
    def __init__(self,bot):
        super().__init__(timeout=900);self.bot=bot;self.add_item(EChannel(bot,'event_panel_channel_id','روم لوحة الفعالية',0));self.add_item(EChannel(bot,'event_leaderboard_channel_id','روم المتصدرين',1));self.add_item(EChannel(bot,'log_channel_id','روم لوق صور الموارد',2));self.add_item(HomeButton(bot,4))
    @discord.ui.button(label='البيانات والشروط',emoji='📝',style=discord.ButtonStyle.primary,row=3)
    async def data(self,i,b):await i.response.send_modal(EventModal(self.bot,await self.bot.db.get_setting('event_name'),await self.bot.db.get_setting('event_description'),await self.bot.db.get_setting('event_terms'),await self.bot.db.get_setting('event_image_url')))
    @discord.ui.button(label='الأزرار',emoji='🔘',style=discord.ButtonStyle.secondary,row=3)
    async def buttons(self,i,b):await i.response.send_modal(EventButtonsModal(self.bot,[await self.bot.db.get_setting('event_join_label'),await self.bot.db.get_setting('event_scan_label'),await self.bot.db.get_setting('event_points_label'),await self.bot.db.get_setting('event_leaderboard_label')]))
    @discord.ui.button(label='نشر/تحديث',emoji='🔄',style=discord.ButtonStyle.success,row=3)
    async def publish(self,i,b):
        if not i.guild:await i.response.send_message('داخل السيرفر فقط.',ephemeral=True);return
        ok,text=await events.publish(self.bot,i.guild);await i.response.send_message(('✅ ' if ok else '⚠️ ')+text,ephemeral=True)

async def ticket_embed(bot):
    ts=await bot.db.ticket_types();return discord.Embed(title='🎫 إعدادات التذاكر',description=f"أنواع التذاكر: **{len(ts)}**\nتحكم بالرسالة والصورة والروم واللوق، ثم أدر الأنواع والـ Category والرتب والأسئلة.")
class TicketPanelModal(discord.ui.Modal,title='لوحة التذاكر'):
    def __init__(self,bot,title,desc,image):
        super().__init__();self.bot=bot;self.titlex=discord.ui.TextInput(label='عنوان اللوحة',default=title[:256]);self.desc=discord.ui.TextInput(label='نص اللوحة',default=desc[:1500],style=discord.TextStyle.paragraph,max_length=1500);self.image=discord.ui.TextInput(label='رابط الصورة (اختياري)',default=image[:1000],required=False,max_length=1000);[self.add_item(x) for x in(self.titlex,self.desc,self.image)]
    async def on_submit(self,i):
        if not good_url(self.image.value.strip()):await i.response.send_message('رابط الصورة غير صحيح.',ephemeral=True);return
        await self.bot.db.set_settings({'ticket_panel_title':self.titlex.value,'ticket_panel_description':self.desc.value,'ticket_panel_image_url':self.image.value.strip()})
        if i.guild:await tickets.refresh_panel(self.bot,i.guild)
        await i.response.edit_message(embed=await ticket_embed(self.bot),view=TicketSettings(self.bot))
class TChannel(discord.ui.ChannelSelect):
    def __init__(self,bot,key,placeholder,row):super().__init__(placeholder=placeholder,channel_types=[discord.ChannelType.text],row=row);self.bot=bot;self.key=key
    async def callback(self,i):await self.bot.db.set_setting(self.key,self.values[0].id);await i.response.send_message(f'✅ تم تحديد {self.values[0].mention}',ephemeral=True)
class AddTypeModal(discord.ui.Modal,title='إضافة زر تذكرة'):
    def __init__(self,bot):
        super().__init__();self.bot=bot
        self.label=discord.ui.TextInput(label='اسم الزر / نوع التذكرة',placeholder='مثال: شكوى',max_length=80)
        self.desc=discord.ui.TextInput(label='الوصف القصير',required=False,max_length=100)
        self.emoji=discord.ui.TextInput(label='الإيموجي',default='🎫',required=False,max_length=20)
        self.welcome=discord.ui.TextInput(label='رسالة الترحيب داخل التذكرة',style=discord.TextStyle.paragraph,required=False,max_length=1500)
        self.questions=discord.ui.TextInput(label='الأسئلة — كل سؤال في سطر (حتى 5)',style=discord.TextStyle.paragraph,required=False,max_length=3000)
        [self.add_item(x) for x in(self.label,self.desc,self.emoji,self.welcome,self.questions)]
    async def on_submit(self,i):
        key='ticket_'+secrets.token_hex(5)
        questions=[x.strip() for x in self.questions.value.splitlines() if x.strip()][:5]
        count=len(await self.bot.db.ticket_types())
        if count>=25:
            await i.response.send_message('⚠️ الحد الأقصى 25 زر تذكرة في اللوحة.',ephemeral=True);return
        await self.bot.db.save_ticket_type({
            'type_id':key,'label':self.label.value.strip(),'description':self.desc.value.strip(),
            'emoji':self.emoji.value or '🎫','welcome_message':self.welcome.value.strip(),
            'questions':json.dumps(questions,ensure_ascii=False),'staff_role_ids':'[]','category_id':0,
            'enabled':1,'sort_order':(count+1)*10
        })
        if i.guild:await tickets.refresh_panel(self.bot,i.guild)
        view=await TypeManager.build(self.bot);await i.response.edit_message(embed=await ticket_embed(self.bot),view=view)
class TypeSelect(discord.ui.Select):
    def __init__(self,bot,types):
        self.bot=bot;opts=[discord.SelectOption(label=t['label'][:100],value=t['type_id'],description='مفعل' if int(t['enabled']) else 'متوقف') for t in types[:25]] or [discord.SelectOption(label='لا توجد أنواع',value='__none__')];super().__init__(placeholder='اختر نوعًا لتعديله',options=opts,row=0)
    async def callback(self,i):
        if self.values[0]=='__none__':await i.response.send_message('أضف نوعًا أولًا.',ephemeral=True);return
        t=await self.bot.db.ticket_type(self.values[0]);await i.response.edit_message(embed=type_embed(t),view=TypeEdit(self.bot,t))
def type_embed(t):
    try:q=len(json.loads(t.get('questions','[]')))
    except:q=0
    return discord.Embed(title=f"🎫 تعديل: {t['label']}",description=f"الحالة: **{'مفعل' if int(t['enabled']) else 'متوقف'}**\nعدد الأسئلة: **{q}**\nCategory ID: `{t.get('category_id',0)}`")
class TypeManager(discord.ui.View):
    def __init__(self,bot):super().__init__(timeout=900);self.bot=bot;self.add_item(HomeButton(bot,4))
    @classmethod
    async def build(cls,bot):v=cls(bot);v.add_item(TypeSelect(bot,await bot.db.ticket_types()));return v
    @discord.ui.button(label='إضافة زر',emoji='➕',style=discord.ButtonStyle.success,row=1)
    async def add(self,i,b):await i.response.send_modal(AddTypeModal(self.bot))
    @discord.ui.button(label='رجوع',style=discord.ButtonStyle.secondary,row=1)
    async def back(self,i,b):await i.response.edit_message(embed=await ticket_embed(self.bot),view=TicketSettings(self.bot))
class TypeDetails(discord.ui.Modal,title='بيانات نوع التذكرة'):
    def __init__(self,bot,t):
        super().__init__();self.bot=bot;self.t=t;self.label=discord.ui.TextInput(label='الاسم',default=t['label'][:80]);self.desc=discord.ui.TextInput(label='الوصف',default=(t.get('description') or '')[:100],required=False);self.emoji=discord.ui.TextInput(label='الإيموجي',default=(t.get('emoji') or '🎫')[:20],required=False);self.welcome=discord.ui.TextInput(label='رسالة الترحيب',default=(t.get('welcome_message') or '')[:1500],style=discord.TextStyle.paragraph,required=False,max_length=1500);[self.add_item(x) for x in(self.label,self.desc,self.emoji,self.welcome)]
    async def on_submit(self,i):
        self.t.update({'label':self.label.value,'description':self.desc.value,'emoji':self.emoji.value or '🎫','welcome_message':self.welcome.value});await self.bot.db.save_ticket_type(self.t)
        if i.guild:await tickets.refresh_panel(self.bot,i.guild)
        t=await self.bot.db.ticket_type(self.t['type_id']);await i.response.edit_message(embed=type_embed(t),view=TypeEdit(self.bot,t))
class TypeQuestions(discord.ui.Modal,title='أسئلة النوع'):
    def __init__(self,bot,t):
        super().__init__();self.bot=bot;self.t=t
        try:q=json.loads(t.get('questions','[]'))
        except:q=[]
        self.q=discord.ui.TextInput(label='كل سؤال في سطر — حد أقصى 5',default='\n'.join(q)[:4000],style=discord.TextStyle.paragraph,required=False,max_length=4000);self.add_item(self.q)
    async def on_submit(self,i):
        self.t['questions']=json.dumps([x.strip() for x in self.q.value.splitlines() if x.strip()][:5],ensure_ascii=False);await self.bot.db.save_ticket_type(self.t);t=await self.bot.db.ticket_type(self.t['type_id']);await i.response.edit_message(embed=type_embed(t),view=TypeEdit(self.bot,t))
class CategorySelect(discord.ui.ChannelSelect):
    def __init__(self,bot,key):super().__init__(placeholder='اختر Category لهذا النوع',channel_types=[discord.ChannelType.category],row=0);self.bot=bot;self.key=key
    async def callback(self,i):t=await self.bot.db.ticket_type(self.key);t['category_id']=self.values[0].id;await self.bot.db.save_ticket_type(t);await i.response.send_message(f'✅ Category: **{self.values[0].name}**',ephemeral=True)
class StaffRoles(discord.ui.RoleSelect):
    def __init__(self,bot,key):super().__init__(placeholder='اختر رتب إدارة هذا النوع',min_values=1,max_values=10,row=1);self.bot=bot;self.key=key
    async def callback(self,i):t=await self.bot.db.ticket_type(self.key);t['staff_role_ids']=dump([r.id for r in self.values]);await self.bot.db.save_ticket_type(t);await i.response.send_message('✅ تم حفظ رتب الإدارة.',ephemeral=True)
class TypeEdit(discord.ui.View):
    def __init__(self,bot,t):super().__init__(timeout=900);self.bot=bot;self.t=t;self.add_item(CategorySelect(bot,t['type_id']));self.add_item(StaffRoles(bot,t['type_id']));self.add_item(HomeButton(bot,4))
    @discord.ui.button(label='الاسم والوصف',emoji='📝',style=discord.ButtonStyle.primary,row=2)
    async def details(self,i,b):await i.response.send_modal(TypeDetails(self.bot,dict(self.t)))
    @discord.ui.button(label='الأسئلة',emoji='❓',style=discord.ButtonStyle.secondary,row=2)
    async def questions(self,i,b):await i.response.send_modal(TypeQuestions(self.bot,dict(self.t)))
    @discord.ui.button(label='تفعيل/إيقاف',style=discord.ButtonStyle.secondary,row=2)
    async def toggle(self,i,b):
        self.t['enabled']=0 if int(self.t['enabled']) else 1;await self.bot.db.save_ticket_type(self.t)
        if i.guild:await tickets.refresh_panel(self.bot,i.guild)
        t=await self.bot.db.ticket_type(self.t['type_id']);await i.response.edit_message(embed=type_embed(t),view=TypeEdit(self.bot,t))
    @discord.ui.button(label='حذف النوع',emoji='🗑️',style=discord.ButtonStyle.danger,row=3)
    async def delete(self,i,b):
        await self.bot.db.delete_ticket_type(self.t['type_id'])
        if i.guild:await tickets.refresh_panel(self.bot,i.guild)
        v=await TypeManager.build(self.bot);await i.response.edit_message(embed=await ticket_embed(self.bot),view=v)
    @discord.ui.button(label='رجوع للأنواع',style=discord.ButtonStyle.secondary,row=3)
    async def back(self,i,b):v=await TypeManager.build(self.bot);await i.response.edit_message(embed=await ticket_embed(self.bot),view=v)
class TicketSettings(discord.ui.View):
    def __init__(self,bot):super().__init__(timeout=900);self.bot=bot;self.add_item(TChannel(bot,'ticket_panel_channel_id','روم لوحة التذاكر',0));self.add_item(TChannel(bot,'ticket_log_channel_id','روم لوق التذاكر',1));self.add_item(HomeButton(bot,4))
    @discord.ui.button(label='نص وصورة اللوحة',emoji='🖼️',style=discord.ButtonStyle.primary,row=2)
    async def panel(self,i,b):await i.response.send_modal(TicketPanelModal(self.bot,await self.bot.db.get_setting('ticket_panel_title'),await self.bot.db.get_setting('ticket_panel_description'),await self.bot.db.get_setting('ticket_panel_image_url')))
    @discord.ui.button(label='أزرار التذاكر',emoji='🎫',style=discord.ButtonStyle.secondary,row=2)
    async def types(self,i,b):v=await TypeManager.build(self.bot);await i.response.edit_message(embed=await ticket_embed(self.bot),view=v)
    @discord.ui.button(label='نشر/تحديث',emoji='🔄',style=discord.ButtonStyle.success,row=2)
    async def publish(self,i,b):
        if not i.guild:await i.response.send_message('داخل السيرفر فقط.',ephemeral=True);return
        ok,text=await tickets.refresh_panel(self.bot,i.guild,True);await i.response.send_message(('✅ ' if ok else '⚠️ ')+text,ephemeral=True)

async def warehouse_embed(bot,guild=None):
    rows=await bot.db.warehouse_locations()
    cid=int(await bot.db.get_setting('warehouse_panel_channel_id','0') or 0)
    ch=guild.get_channel(cid) if guild else None
    return discord.Embed(
        title='📦 إعدادات المخازن',
        description=(
            f"**عدد المستودعات:** {len(rows)}/20\n"
            f"**روم اللوحة:** {ch.mention if isinstance(ch,discord.TextChannel) else 'غير محدد'}\n\n"
            'كل مستودع يظهر داخل اللوحة بموارده الثمانية، **بدون مجموع**.\n'
            'اسم المستودع هو نفسه اسم الزر. عند إرسال صورة جديدة يتم استبدال القيم القديمة بالكامل.'
        )
    )

class WarehousePanelModal(discord.ui.Modal,title='لوحة المخازن'):
    def __init__(self,bot,title,desc,image):
        super().__init__();self.bot=bot
        self.titlex=discord.ui.TextInput(label='عنوان اللوحة',default=title[:256],max_length=256)
        self.desc=discord.ui.TextInput(label='نص اللوحة',default=desc[:4000],style=discord.TextStyle.paragraph,max_length=4000)
        self.image=discord.ui.TextInput(label='رابط الصورة (اختياري)',default=image[:1000],required=False,max_length=1000)
        [self.add_item(x) for x in (self.titlex,self.desc,self.image)]
    async def on_submit(self,i):
        if not good_url(self.image.value.strip()):
            await i.response.send_message('رابط الصورة غير صحيح.',ephemeral=True);return
        await self.bot.db.set_settings({
            'warehouse_panel_title':self.titlex.value.strip(),
            'warehouse_panel_description':self.desc.value.strip(),
            'warehouse_panel_image_url':self.image.value.strip(),
        })
        if i.guild:await warehouses.refresh_panel(self.bot,i.guild,False)
        await i.response.edit_message(embed=await warehouse_embed(self.bot,i.guild),view=WarehouseSettings(self.bot))

class WarehouseChannel(discord.ui.ChannelSelect):
    def __init__(self,bot):
        super().__init__(placeholder='حدد روم لوحة المخازن',channel_types=[discord.ChannelType.text],row=0);self.bot=bot
    async def callback(self,i):
        await self.bot.db.set_settings({'warehouse_panel_channel_id':self.values[0].id,'warehouse_panel_message_id':'0'})
        await i.response.edit_message(embed=await warehouse_embed(self.bot,i.guild),view=WarehouseSettings(self.bot))

class AddWarehouseModal(discord.ui.Modal,title='إضافة مستودع'):
    def __init__(self,bot):
        super().__init__();self.bot=bot
        self.label=discord.ui.TextInput(label='اسم المستودع / اسم الزر',placeholder='مثال: مستودع ساندي',max_length=80)
        self.add_item(self.label)
    async def on_submit(self,i):
        label=self.label.value.strip()
        rows=await self.bot.db.warehouse_locations()
        if len(rows)>=20:
            await i.response.send_message('⚠️ الحد الأقصى 20 مستودعًا في اللوحة.',ephemeral=True);return
        if any(r['label'].strip().casefold()==label.casefold() for r in rows):
            await i.response.send_message('⚠️ يوجد مستودع بهذا الاسم بالفعل.',ephemeral=True);return
        wid='wh_'+secrets.token_hex(5)
        await self.bot.db.add_warehouse(wid,label,(len(rows)+1)*10)
        if i.guild:await warehouses.refresh_panel(self.bot,i.guild,False)
        await i.response.edit_message(embed=await warehouse_embed(self.bot,i.guild),view=WarehouseSettings(self.bot))

class WarehouseSelect(discord.ui.Select):
    def __init__(self,bot,rows):
        self.bot=bot
        options=[discord.SelectOption(label=r['label'][:100],value=r['warehouse_id'],emoji='📦') for r in rows[:20]]
        super().__init__(placeholder='اختر مستودعًا للتعديل',options=options,row=0)
    async def callback(self,i):
        row=await self.bot.db.warehouse_location(self.values[0])
        if not row:
            await i.response.send_message('المستودع غير موجود.',ephemeral=True);return
        await i.response.edit_message(embed=warehouse_item_embed(row),view=WarehouseEditView(self.bot,row))

class WarehouseManagerView(discord.ui.View):
    def __init__(self,bot,rows):
        super().__init__(timeout=900);self.bot=bot;self.add_item(WarehouseSelect(bot,rows));self.add_item(HomeButton(bot,4))
    @discord.ui.button(label='رجوع للمخازن',style=discord.ButtonStyle.secondary,row=1)
    async def back(self,i,b):await i.response.edit_message(embed=await warehouse_embed(self.bot,i.guild),view=WarehouseSettings(self.bot))


def warehouse_item_embed(row):
    return discord.Embed(title=f"📦 {row['label']}",description='يمكنك تغيير اسم المستودع/الزر أو حذفه. حذف المستودع يحذف قيمه الحالية أيضًا.')

class RenameWarehouseModal(discord.ui.Modal,title='تعديل اسم المستودع'):
    def __init__(self,bot,row):
        super().__init__();self.bot=bot;self.row=row
        self.label=discord.ui.TextInput(label='اسم المستودع / اسم الزر',default=row['label'][:80],max_length=80)
        self.add_item(self.label)
    async def on_submit(self,i):
        label=self.label.value.strip()
        rows=await self.bot.db.warehouse_locations()
        if any(r['warehouse_id']!=self.row['warehouse_id'] and r['label'].strip().casefold()==label.casefold() for r in rows):
            await i.response.send_message('⚠️ يوجد مستودع بهذا الاسم بالفعل.',ephemeral=True);return
        await self.bot.db.update_warehouse(self.row['warehouse_id'],label=label)
        row=await self.bot.db.warehouse_location(self.row['warehouse_id'])
        if i.guild:await warehouses.refresh_panel(self.bot,i.guild,False)
        await i.response.edit_message(embed=warehouse_item_embed(row),view=WarehouseEditView(self.bot,row))

class WarehouseEditView(discord.ui.View):
    def __init__(self,bot,row):
        super().__init__(timeout=900);self.bot=bot;self.row=row;self.add_item(HomeButton(bot,4))
    @discord.ui.button(label='تغيير الاسم / الزر',emoji='✏️',style=discord.ButtonStyle.primary,row=0)
    async def rename(self,i,b):await i.response.send_modal(RenameWarehouseModal(self.bot,self.row))
    @discord.ui.button(label='حذف المستودع',emoji='🗑️',style=discord.ButtonStyle.danger,row=0)
    async def delete(self,i,b):
        await self.bot.db.delete_warehouse(self.row['warehouse_id'])
        if i.guild:await warehouses.refresh_panel(self.bot,i.guild,False)
        await i.response.edit_message(embed=await warehouse_embed(self.bot,i.guild),view=WarehouseSettings(self.bot))
    @discord.ui.button(label='رجوع للقائمة',style=discord.ButtonStyle.secondary,row=1)
    async def back(self,i,b):
        rows=await self.bot.db.warehouse_locations()
        if rows:await i.response.edit_message(embed=await warehouse_embed(self.bot,i.guild),view=WarehouseManagerView(self.bot,rows))
        else:await i.response.edit_message(embed=await warehouse_embed(self.bot,i.guild),view=WarehouseSettings(self.bot))

class WarehouseSettings(discord.ui.View):
    def __init__(self,bot):
        super().__init__(timeout=900);self.bot=bot;self.add_item(WarehouseChannel(bot));self.add_item(HomeButton(bot,4))
    @discord.ui.button(label='نص وصورة اللوحة',emoji='🖼️',style=discord.ButtonStyle.primary,row=1)
    async def panel(self,i,b):
        await i.response.send_modal(WarehousePanelModal(
            self.bot,
            await self.bot.db.get_setting('warehouse_panel_title'),
            await self.bot.db.get_setting('warehouse_panel_description'),
            await self.bot.db.get_setting('warehouse_panel_image_url'),
        ))
    @discord.ui.button(label='إضافة مستودع',emoji='➕',style=discord.ButtonStyle.success,row=1)
    async def add(self,i,b):await i.response.send_modal(AddWarehouseModal(self.bot))
    @discord.ui.button(label='إدارة المستودعات',emoji='📦',style=discord.ButtonStyle.secondary,row=2)
    async def manage(self,i,b):
        rows=await self.bot.db.warehouse_locations()
        if not rows:
            await i.response.send_message('لا توجد مستودعات. أضف مستودعًا أولًا.',ephemeral=True);return
        await i.response.edit_message(embed=await warehouse_embed(self.bot,i.guild),view=WarehouseManagerView(self.bot,rows))
    @discord.ui.button(label='نشر/تحديث اللوحة',emoji='🔄',style=discord.ButtonStyle.success,row=2)
    async def publish(self,i,b):
        if not i.guild:
            await i.response.send_message('داخل السيرفر فقط.',ephemeral=True);return
        ok,text=await warehouses.refresh_panel(self.bot,i.guild,True)
        await i.response.send_message(('✅ ' if ok else '⚠️ ')+text,ephemeral=True)


async def workshop_embed(bot,guild=None):
    panel_id=int(await bot.db.get_setting('workshop_panel_channel_id','0') or 0)
    log_id=int(await bot.db.get_setting('workshop_log_channel_id','0') or 0)
    lead_id=int(await bot.db.get_setting('workshop_leaderboard_channel_id','0') or 0)
    def chname(cid):
        ch=guild.get_channel(cid) if guild and cid else None
        return ch.mention if isinstance(ch,discord.TextChannel) else 'غير محدد'
    return discord.Embed(
        title='🛠️ إعدادات نظام الورش',
        description=(
            f"**روم اللوحة:** {chname(panel_id)}\n"
            f"**روم اللوق:** {chname(log_id)}\n"
            f"**روم أكثر المتفاعلين:** {chname(lead_id)}\n\n"
            'الخدمات: **تعديل مركبة** و **بيع عدة تصليح**.\n'
            'تعديل المركبة يطلب نوع التعديل ثم صورة الفاتورة وصورة السيارة.'
        )
    )

class WorkshopPanelModal(discord.ui.Modal,title='لوحة الورش'):
    def __init__(self,bot,title,desc,image):
        super().__init__();self.bot=bot
        self.titlex=discord.ui.TextInput(label='عنوان اللوحة',default=title[:256],max_length=256)
        self.desc=discord.ui.TextInput(label='نص اللوحة',default=desc[:4000],style=discord.TextStyle.paragraph,max_length=4000)
        self.image=discord.ui.TextInput(label='رابط الصورة (اختياري)',default=image[:1000],required=False,max_length=1000)
        [self.add_item(x) for x in (self.titlex,self.desc,self.image)]
    async def on_submit(self,i):
        if not good_url(self.image.value.strip()):await i.response.send_message('رابط الصورة غير صحيح.',ephemeral=True);return
        await self.bot.db.set_settings({
            'workshop_panel_title':self.titlex.value.strip(),
            'workshop_panel_description':self.desc.value.strip(),
            'workshop_panel_image_url':self.image.value.strip(),
        })
        if i.guild:await workshops.refresh_panel(self.bot,i.guild,False)
        await i.response.edit_message(embed=await workshop_embed(self.bot,i.guild),view=WorkshopSettings(self.bot))

class WorkshopChannel(discord.ui.ChannelSelect):
    def __init__(self,bot,key,placeholder,row):
        super().__init__(placeholder=placeholder,channel_types=[discord.ChannelType.text],row=row);self.bot=bot;self.key=key
    async def callback(self,i):
        values={self.key:self.values[0].id}
        if self.key=='workshop_panel_channel_id':values['workshop_panel_message_id']='0'
        if self.key=='workshop_leaderboard_channel_id':values['workshop_leaderboard_message_id']='0'
        await self.bot.db.set_settings(values)
        await i.response.edit_message(embed=await workshop_embed(self.bot,i.guild),view=WorkshopSettings(self.bot))

class WorkshopResetConfirm(discord.ui.View):
    def __init__(self,bot,uid):super().__init__(timeout=60);self.bot=bot;self.uid=uid
    async def interaction_check(self,i):
        if i.user.id!=self.uid:await i.response.send_message('هذا التأكيد يخص الإداري الذي طلبه.',ephemeral=True);return False
        return True
    @discord.ui.button(label='تأكيد التصفير',emoji='🗑️',style=discord.ButtonStyle.danger)
    async def confirm(self,i,b):
        await self.bot.db.reset_workshops()
        if i.guild:await workshops.refresh_leaderboard(self.bot,i.guild,True)
        await i.response.edit_message(content='✅ تم تصفير نقاط تفاعل الورش.',embed=None,view=None)
    @discord.ui.button(label='إلغاء',style=discord.ButtonStyle.secondary)
    async def cancel(self,i,b):await i.response.edit_message(content='تم إلغاء التصفير.',embed=None,view=None)

class WorkshopSettings(discord.ui.View):
    def __init__(self,bot):
        super().__init__(timeout=900);self.bot=bot
        self.add_item(WorkshopChannel(bot,'workshop_panel_channel_id','روم لوحة الورش',0))
        self.add_item(WorkshopChannel(bot,'workshop_log_channel_id','روم لوق صور الورش',1))
        self.add_item(WorkshopChannel(bot,'workshop_leaderboard_channel_id','روم أكثر المتفاعلين',2))
        self.add_item(HomeButton(bot,4))
    @discord.ui.button(label='نص وصورة اللوحة',emoji='🖼️',style=discord.ButtonStyle.primary,row=3)
    async def panel(self,i,b):
        await i.response.send_modal(WorkshopPanelModal(
            self.bot,
            await self.bot.db.get_setting('workshop_panel_title'),
            await self.bot.db.get_setting('workshop_panel_description'),
            await self.bot.db.get_setting('workshop_panel_image_url'),
        ))
    @discord.ui.button(label='نشر/تحديث',emoji='🔄',style=discord.ButtonStyle.success,row=3)
    async def publish(self,i,b):
        if not i.guild:await i.response.send_message('داخل السيرفر فقط.',ephemeral=True);return
        ok,text=await workshops.refresh_all(self.bot,i.guild,True)
        await i.response.send_message(('✅ ' if ok else '⚠️ ')+text,ephemeral=True)
    @discord.ui.button(label='تصفير التفاعل',emoji='🗑️',style=discord.ButtonStyle.danger,row=3)
    async def reset(self,i,b):
        await i.response.send_message('⚠️ هل تريد تصفير ترتيب أكثر المتفاعلين للورش؟',view=WorkshopResetConfirm(self.bot,i.user.id),ephemeral=True)

async def attendance_embed(bot):return discord.Embed(title='🕒 إعدادات الدخول والخروج',description=f"رتب الموظفين: **{len(ids(await bot.db.get_setting('attendance_employee_role_ids','[]')))}**\nرتب الإدارة: **{len(ids(await bot.db.get_setting('attendance_admin_role_ids','[]')))}**\nاضبط الرتب والرومات ونص اللوحة ثم انشر اللوحات.")
class AttPanelModal(discord.ui.Modal,title='لوحة الحضور'):
    def __init__(self,bot,title,desc,image):
        super().__init__();self.bot=bot;self.titlex=discord.ui.TextInput(label='العنوان',default=title[:256]);self.desc=discord.ui.TextInput(label='النص',default=desc[:4000],style=discord.TextStyle.paragraph,max_length=4000);self.image=discord.ui.TextInput(label='رابط الصورة (اختياري)',default=image[:1000],required=False,max_length=1000);[self.add_item(x) for x in(self.titlex,self.desc,self.image)]
    async def on_submit(self,i):
        if not good_url(self.image.value.strip()):await i.response.send_message('رابط الصورة غير صحيح.',ephemeral=True);return
        await self.bot.db.set_settings({'attendance_panel_title':self.titlex.value,'attendance_panel_description':self.desc.value,'attendance_panel_image_url':self.image.value.strip()})
        if i.guild:await attendance.refresh_panel(self.bot,i.guild)
        await i.response.edit_message(embed=await attendance_embed(self.bot),view=AttendanceSettings(self.bot))
class EmpRoles(discord.ui.RoleSelect):
    def __init__(self,bot):super().__init__(placeholder='حدد رتبة/رتب الموظفين',min_values=1,max_values=10,row=0);self.bot=bot
    async def callback(self,i):
        await self.bot.db.set_setting('attendance_employee_role_ids',dump([r.id for r in self.values]))
        if i.guild:
            await attendance.refresh_staff(self.bot,i.guild,True)
        await i.response.send_message('✅ تم حفظ رتب الموظفين.',ephemeral=True)
class AdminRoles(discord.ui.RoleSelect):
    def __init__(self,bot):super().__init__(placeholder='حدد رتبة/رتب الإدارة',min_values=1,max_values=10,row=1);self.bot=bot
    async def callback(self,i):await self.bot.db.set_setting('attendance_admin_role_ids',dump([r.id for r in self.values]));await i.response.send_message('✅ تم حفظ رتب الإدارة.',ephemeral=True)
class RoleView(discord.ui.View):
    def __init__(self,bot):super().__init__(timeout=900);self.bot=bot;self.add_item(EmpRoles(bot));self.add_item(AdminRoles(bot));self.add_item(HomeButton(bot,4))
    @discord.ui.button(label='رجوع',style=discord.ButtonStyle.secondary,row=2)
    async def back(self,i,b):await i.response.edit_message(embed=await attendance_embed(self.bot),view=AttendanceSettings(self.bot))
class AChannel(discord.ui.ChannelSelect):
    def __init__(self,bot,key,placeholder,row):super().__init__(placeholder=placeholder,channel_types=[discord.ChannelType.text],row=row);self.bot=bot;self.key=key
    async def callback(self,i):await self.bot.db.set_setting(self.key,self.values[0].id);await i.response.send_message(f'✅ تم تحديد {self.values[0].mention}',ephemeral=True)
class ChannelView(discord.ui.View):
    def __init__(self,bot):
        super().__init__(timeout=900);self.bot=bot;self.add_item(AChannel(bot,'attendance_panel_channel_id','روم لوحة الدخول والخروج',0));self.add_item(AChannel(bot,'attendance_status_channel_id','روم المسجلين والغفوة',1));self.add_item(AChannel(bot,'staff_board_channel_id','روم لوحة الموظفين والساعات',2));self.add_item(AChannel(bot,'staff_log_channel_id','روم لوق الموظفين والرسائل',3));self.add_item(HomeButton(bot,4))
    @discord.ui.button(label='رجوع',style=discord.ButtonStyle.secondary,row=4)
    async def back(self,i,b):await i.response.edit_message(embed=await attendance_embed(self.bot),view=AttendanceSettings(self.bot))

class AttendanceResetConfirm(discord.ui.View):
    def __init__(self,bot,uid):super().__init__(timeout=60);self.bot=bot;self.uid=uid
    async def interaction_check(self,i):
        if i.user.id!=self.uid:await i.response.send_message('هذا التأكيد يخص الإداري الذي طلبه.',ephemeral=True);return False
        return True
    @discord.ui.button(label='تأكيد تصفير الساعات',emoji='🗑️',style=discord.ButtonStyle.danger)
    async def confirm(self,i,b):
        await self.bot.db.reset_attendance()
        if i.guild:
            await attendance.refresh_status(self.bot,i.guild,True)
            await attendance.refresh_staff(self.bot,i.guild,True)
        await i.response.edit_message(content='✅ تم تصفير ساعات الحضور وإنهاء الجلسات الحالية.',embed=None,view=None)
    @discord.ui.button(label='إلغاء',style=discord.ButtonStyle.secondary)
    async def cancel(self,i,b):await i.response.edit_message(content='تم إلغاء التصفير.',embed=None,view=None)

class AttendanceSettings(discord.ui.View):
    def __init__(self,bot):super().__init__(timeout=900);self.bot=bot;self.add_item(HomeButton(bot,4))
    @discord.ui.button(label='الرتب',emoji='👮',style=discord.ButtonStyle.primary,row=0)
    async def roles(self,i,b):await i.response.edit_message(embed=await attendance_embed(self.bot),view=RoleView(self.bot))
    @discord.ui.button(label='الرومات',emoji='#️⃣',style=discord.ButtonStyle.secondary,row=0)
    async def channels(self,i,b):await i.response.edit_message(embed=await attendance_embed(self.bot),view=ChannelView(self.bot))
    @discord.ui.button(label='نص وصورة اللوحة',emoji='🖼️',style=discord.ButtonStyle.secondary,row=1)
    async def panel(self,i,b):await i.response.send_modal(AttPanelModal(self.bot,await self.bot.db.get_setting('attendance_panel_title'),await self.bot.db.get_setting('attendance_panel_description'),await self.bot.db.get_setting('attendance_panel_image_url')))
    @discord.ui.button(label='نشر/تحديث اللوحات',emoji='🔄',style=discord.ButtonStyle.success,row=1)
    async def publish(self,i,b):
        if not i.guild:await i.response.send_message('داخل السيرفر فقط.',ephemeral=True);return
        ok,text=await attendance.refresh_all(self.bot,i.guild,True);await i.response.send_message(('✅ ' if ok else '⚠️ ')+text,ephemeral=True)
    @discord.ui.button(label='تصفير الساعات',emoji='🗑️',style=discord.ButtonStyle.danger,row=2)
    async def reset_hours(self,i,b):
        await i.response.send_message('⚠️ سيتم تصفير جميع ساعات الحضور وإنهاء الجلسات الحالية. متأكد؟',view=AttendanceResetConfirm(self.bot,i.user.id),ephemeral=True)

def staff_embed():return discord.Embed(title='👥 إعدادات الموظفين',description='لوحة ثابتة لكل من يحمل رتبة الموظف، تعرض ساعات المباشرة والملاحظة بجانب الاسم.\nتحديد الروم والرتب من قسم الدخول والخروج.')
class StaffSettings(discord.ui.View):
    def __init__(self,bot):super().__init__(timeout=900);self.bot=bot;self.add_item(HomeButton(bot,4))
    @discord.ui.button(label='تحديث لوحة الموظفين',emoji='🔄',style=discord.ButtonStyle.success,row=0)
    async def refresh(self,i,b):
        if i.guild:await attendance.refresh_staff(self.bot,i.guild,True)
        await i.response.send_message('✅ تم تحديث لوحة الموظفين.',ephemeral=True)
    @discord.ui.button(label='إعدادات الحضور',emoji='🕒',style=discord.ButtonStyle.secondary,row=0)
    async def att(self,i,b):await i.response.edit_message(embed=await attendance_embed(self.bot),view=AttendanceSettings(self.bot))

async def general_embed(bot,guild):
    roleids=ids(await bot.db.get_setting('bot_admin_role_ids','[]'));roles=[]
    if guild:
        for rid in roleids:
            r=guild.get_role(rid)
            if r:roles.append(r.mention)
    return discord.Embed(title='⚙️ الإعدادات العامة',description=f"**مالك البوت الكامل:** <@{bot.owner_user_id}>\n**رتب إدارة البوت:** {'، '.join(roles) if roles else 'غير محددة'}\nمالك البوت يملك صلاحية كاملة دائمًا.")
class BotAdminRoles(discord.ui.RoleSelect):
    def __init__(self,bot):super().__init__(placeholder='حدد رتب إدارة البوت',min_values=1,max_values=10,row=0);self.bot=bot
    async def callback(self,i):await self.bot.db.set_setting('bot_admin_role_ids',dump([r.id for r in self.values]));await i.response.edit_message(embed=await general_embed(self.bot,i.guild),view=GeneralSettings(self.bot))
class GeneralSettings(discord.ui.View):
    def __init__(self,bot):super().__init__(timeout=900);self.add_item(BotAdminRoles(bot));self.add_item(HomeButton(bot,4))
