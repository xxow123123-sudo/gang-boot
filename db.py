# -*- coding: utf-8 -*-
import json
from datetime import datetime, timezone
from typing import Optional
import aiosqlite

RESOURCE_NAMES = ("steel","aluminum","rubber","metalscrap","iron","plastic","copper","glass")


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def total_for(row: dict) -> int:
    return sum(int(row.get(k, 0) or 0) for k in RESOURCE_NAMES) + int(row.get("admin_adjustment", 0) or 0)


class Database:
    def __init__(self, path: str):
        self.path = path

    async def connect(self):
        db = await aiosqlite.connect(self.path)
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA journal_mode=WAL;")
        await db.execute("PRAGMA foreign_keys=ON;")
        return db

    async def init(self):
        db = await self.connect()
        try:
            await db.executescript("""
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS balances(
                user_id INTEGER PRIMARY KEY, steel INTEGER NOT NULL DEFAULT 0, aluminum INTEGER NOT NULL DEFAULT 0,
                rubber INTEGER NOT NULL DEFAULT 0, metalscrap INTEGER NOT NULL DEFAULT 0, iron INTEGER NOT NULL DEFAULT 0,
                plastic INTEGER NOT NULL DEFAULT 0, copper INTEGER NOT NULL DEFAULT 0, glass INTEGER NOT NULL DEFAULT 0,
                admin_adjustment INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS submissions(
                id INTEGER PRIMARY KEY AUTOINCREMENT,event_id INTEGER NOT NULL,user_id INTEGER NOT NULL,image_hash TEXT NOT NULL,
                steel INTEGER NOT NULL,aluminum INTEGER NOT NULL,rubber INTEGER NOT NULL,metalscrap INTEGER NOT NULL,
                iron INTEGER NOT NULL,plastic INTEGER NOT NULL,copper INTEGER NOT NULL,glass INTEGER NOT NULL,created_at TEXT NOT NULL,
                UNIQUE(event_id,image_hash));
            CREATE TABLE IF NOT EXISTS audit_log(
                id INTEGER PRIMARY KEY AUTOINCREMENT,event_id INTEGER NOT NULL,admin_id INTEGER NOT NULL,target_user_id INTEGER NOT NULL,
                action TEXT NOT NULL,resource TEXT,amount INTEGER NOT NULL,created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS archived_results(
                event_id INTEGER NOT NULL,user_id INTEGER NOT NULL,steel INTEGER NOT NULL,aluminum INTEGER NOT NULL,rubber INTEGER NOT NULL,
                metalscrap INTEGER NOT NULL,iron INTEGER NOT NULL,plastic INTEGER NOT NULL,copper INTEGER NOT NULL,glass INTEGER NOT NULL,
                admin_adjustment INTEGER NOT NULL,total INTEGER NOT NULL,archived_at TEXT NOT NULL,PRIMARY KEY(event_id,user_id));
            CREATE TABLE IF NOT EXISTS event_participants(
                event_id INTEGER NOT NULL,user_id INTEGER NOT NULL,accepted_at TEXT NOT NULL,PRIMARY KEY(event_id,user_id));
            CREATE TABLE IF NOT EXISTS ticket_types(
                type_id TEXT PRIMARY KEY,label TEXT NOT NULL,description TEXT NOT NULL DEFAULT '',emoji TEXT NOT NULL DEFAULT '🎫',
                category_id INTEGER NOT NULL DEFAULT 0,staff_role_ids TEXT NOT NULL DEFAULT '[]',welcome_message TEXT NOT NULL DEFAULT '',
                questions TEXT NOT NULL DEFAULT '[]',enabled INTEGER NOT NULL DEFAULT 1,sort_order INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS tickets(
                id INTEGER PRIMARY KEY AUTOINCREMENT,guild_id INTEGER NOT NULL,channel_id INTEGER NOT NULL UNIQUE,user_id INTEGER NOT NULL,
                type_id TEXT NOT NULL,answers TEXT NOT NULL DEFAULT '{}',status TEXT NOT NULL DEFAULT 'open',created_at TEXT NOT NULL,
                closed_at TEXT,closed_by INTEGER);
            CREATE TABLE IF NOT EXISTS attendance_sessions(
                user_id INTEGER PRIMARY KEY,state TEXT NOT NULL,login_at TEXT NOT NULL,break_started_at TEXT,
                break_seconds INTEGER NOT NULL DEFAULT 0,updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS attendance_totals(
                user_id INTEGER PRIMARY KEY,total_seconds INTEGER NOT NULL DEFAULT 0,updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS attendance_log(
                id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,action TEXT NOT NULL,actor_id INTEGER,
                seconds INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS staff_notes(
                user_id INTEGER PRIMARY KEY,note TEXT NOT NULL,updated_by INTEGER NOT NULL,updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS warehouse_locations(
                warehouse_id TEXT PRIMARY KEY,label TEXT NOT NULL,enabled INTEGER NOT NULL DEFAULT 1,
                sort_order INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS warehouse_stock(
                warehouse_id TEXT PRIMARY KEY,steel INTEGER NOT NULL DEFAULT 0,aluminum INTEGER NOT NULL DEFAULT 0,
                rubber INTEGER NOT NULL DEFAULT 0,metalscrap INTEGER NOT NULL DEFAULT 0,iron INTEGER NOT NULL DEFAULT 0,
                plastic INTEGER NOT NULL DEFAULT 0,copper INTEGER NOT NULL DEFAULT 0,glass INTEGER NOT NULL DEFAULT 0,
                updated_by INTEGER,updated_at TEXT NOT NULL,
                FOREIGN KEY(warehouse_id) REFERENCES warehouse_locations(warehouse_id) ON DELETE CASCADE);
            CREATE TABLE IF NOT EXISTS bot_meta(
                key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS workshop_entries(
                id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,service TEXT NOT NULL,
                modification_type TEXT NOT NULL DEFAULT '',invoice_filename TEXT NOT NULL DEFAULT '',
                car_filename TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL);
            """)
            defaults = {
                "active":"0","current_event_id":"0","log_channel_id":"0",
                "event_name":"فعالية جمع الموارد",
                "event_description":"اضغط دخول الفعالية أولًا، وافق على الشروط، ثم ارفع صور الموارد.",
                "event_terms":"1) الالتزام بقوانين السيرفر.\n2) يمنع إرسال صورة مكررة.\n3) يجب أن تكون أرقام Owned واضحة.",
                "event_image_url":"","event_panel_channel_id":"0","event_panel_message_id":"0",
                "event_leaderboard_channel_id":"0","event_leaderboard_message_id":"0",
                "event_join_label":"دخول الفعالية","event_scan_label":"حساب الموارد","event_points_label":"نقاطي","event_leaderboard_label":"الترتيب",
                "ticket_panel_title":"🎫 التذاكر","ticket_panel_description":"اختر نوع التذكرة من الأزرار بالأسفل.",
                "ticket_panel_image_url":"","ticket_panel_channel_id":"0","ticket_panel_message_id":"0","ticket_log_channel_id":"0",
                "attendance_employee_role_ids":"[]","attendance_admin_role_ids":"[]",
                "attendance_panel_title":"🕒 تسجيل الدخول والخروج",
                "attendance_panel_description":"استخدم الأزرار لتسجيل الدخول والخروج أو بدء/إنهاء الغفوة.",
                "attendance_panel_image_url":"","attendance_panel_channel_id":"0","attendance_panel_message_id":"0",
                "attendance_status_channel_id":"0","attendance_status_message_id":"0",
                "staff_board_channel_id":"0","staff_board_message_id":"0","staff_log_channel_id":"0",
                "bot_admin_role_ids":"[]",
                "warehouse_panel_title":"📦 حالة المخازن",
                "warehouse_panel_description":"اختر المستودع من الأزرار بالأسفل ثم أرسل صورة الموارد لتحديث بياناته.",
                "warehouse_panel_image_url":"","warehouse_panel_channel_id":"0","warehouse_panel_message_id":"0",
                "workshop_panel_title":"🛠️ نظام الورش",
                "workshop_panel_description":"اضغط الزر وسجل الخدمة التي قمت ببيعها.",
                "workshop_panel_image_url":"","workshop_panel_channel_id":"0","workshop_panel_message_id":"0",
                "workshop_log_channel_id":"0","workshop_leaderboard_channel_id":"0","workshop_leaderboard_message_id":"0",
            }
            for k,v in defaults.items():
                await db.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)",(k,v))
            # migrate old event panel settings when present
            for new,old in (("event_panel_channel_id","panel_channel_id"),("event_panel_message_id","panel_message_id")):
                cur=await db.execute("SELECT value FROM settings WHERE key=?",(new,)); r=await cur.fetchone()
                if r and r["value"]=="0":
                    cur=await db.execute("SELECT value FROM settings WHERE key=?",(old,)); oldr=await cur.fetchone()
                    if oldr and oldr["value"]!="0": await db.execute("UPDATE settings SET value=? WHERE key=?",(oldr["value"],new))
            await db.execute("INSERT OR IGNORE INTO ticket_types(type_id,label,description,emoji,welcome_message,questions,sort_order) VALUES(?,?,?,?,?,?,?)",
                ("application","تقديم","التقديم وفتح طلب جديد","📣","مرحبًا، تم فتح تذكرة التقديم الخاصة بك.",json.dumps(["الاسم؟","العمر؟","خبرتك السابقة؟"],ensure_ascii=False),10))
            await db.execute("INSERT OR IGNORE INTO ticket_types(type_id,label,description,emoji,welcome_message,questions,sort_order) VALUES(?,?,?,?,?,?,?)",
                ("inquiry","استفسارات","استفسار أو مشكلة","❓","مرحبًا، اكتب استفسارك وسيتم الرد عليك من الإدارة.","[]",20))
            await db.commit()
        finally: await db.close()

    async def get_setting(self,key,default=""):
        db=await self.connect()
        try:
            cur=await db.execute("SELECT value FROM settings WHERE key=?",(key,)); r=await cur.fetchone(); return r["value"] if r else default
        finally: await db.close()

    async def set_setting(self,key,value):
        db=await self.connect()
        try:
            await db.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(key,str(value))); await db.commit()
        finally: await db.close()

    async def set_settings(self,values:dict):
        db=await self.connect()
        try:
            for k,v in values.items(): await db.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(k,str(v)))
            await db.commit()
        finally: await db.close()

    async def is_active(self): return (await self.get_setting("active","0"))=="1"
    async def current_event_id(self): return int(await self.get_setting("current_event_id","0") or 0)

    async def start_event(self):
        db=await self.connect()
        try:
            await db.execute("BEGIN IMMEDIATE")
            cur=await db.execute("SELECT value FROM settings WHERE key='active'"); active=(await cur.fetchone())["value"]=="1"
            cur=await db.execute("SELECT value FROM settings WHERE key='current_event_id'"); eid=int((await cur.fetchone())["value"])
            if active: await db.rollback(); return False,eid
            eid+=1
            await db.execute("UPDATE settings SET value='1' WHERE key='active'"); await db.execute("UPDATE settings SET value=? WHERE key='current_event_id'",(str(eid),))
            await db.execute("UPDATE balances SET steel=0,aluminum=0,rubber=0,metalscrap=0,iron=0,plastic=0,copper=0,glass=0,admin_adjustment=0,updated_at=?",(now_iso(),))
            await db.commit(); return True,eid
        finally: await db.close()

    async def end_event(self):
        db=await self.connect()
        try:
            await db.execute("BEGIN IMMEDIATE")
            cur=await db.execute("SELECT value FROM settings WHERE key='active'"); active=(await cur.fetchone())["value"]=="1"
            cur=await db.execute("SELECT value FROM settings WHERE key='current_event_id'"); eid=int((await cur.fetchone())["value"])
            if not active: await db.rollback(); return None
            cur=await db.execute("SELECT * FROM balances"); rows=[dict(r) for r in await cur.fetchall()]; archived=now_iso()
            for r in rows:
                await db.execute("INSERT OR REPLACE INTO archived_results(event_id,user_id,steel,aluminum,rubber,metalscrap,iron,plastic,copper,glass,admin_adjustment,total,archived_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (eid,r["user_id"],r["steel"],r["aluminum"],r["rubber"],r["metalscrap"],r["iron"],r["plastic"],r["copper"],r["glass"],r["admin_adjustment"],total_for(r),archived))
            await db.execute("UPDATE balances SET steel=0,aluminum=0,rubber=0,metalscrap=0,iron=0,plastic=0,copper=0,glass=0,admin_adjustment=0,updated_at=?",(now_iso(),))
            await db.execute("UPDATE settings SET value='0' WHERE key='active'"); await db.commit(); return eid,rows
        finally: await db.close()

    async def accept_terms(self,eid,uid):
        db=await self.connect()
        try: await db.execute("INSERT OR IGNORE INTO event_participants(event_id,user_id,accepted_at) VALUES(?,?,?)",(eid,uid,now_iso())); await db.commit()
        finally: await db.close()
    async def is_participant(self,eid,uid):
        db=await self.connect()
        try: cur=await db.execute("SELECT 1 FROM event_participants WHERE event_id=? AND user_id=?",(eid,uid)); return (await cur.fetchone()) is not None
        finally: await db.close()
    async def is_duplicate(self,eid,h):
        db=await self.connect()
        try: cur=await db.execute("SELECT 1 FROM submissions WHERE event_id=? AND image_hash=?",(eid,h)); return (await cur.fetchone()) is not None
        finally: await db.close()

    async def add_submission(self,eid,uid,h,res):
        db=await self.connect()
        try:
            await db.execute("BEGIN IMMEDIATE")
            cur=await db.execute("SELECT value FROM settings WHERE key='active'"); active=(await cur.fetchone())["value"]=="1"
            cur=await db.execute("SELECT value FROM settings WHERE key='current_event_id'"); current=int((await cur.fetchone())["value"])
            if not active: await db.rollback(); return False,"inactive"
            if current!=eid: await db.rollback(); return False,"event_changed"
            try:
                await db.execute("INSERT INTO submissions(event_id,user_id,image_hash,steel,aluminum,rubber,metalscrap,iron,plastic,copper,glass,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (eid,uid,h,res["steel"],res["aluminum"],res["rubber"],res["metalscrap"],res["iron"],res["plastic"],res["copper"],res["glass"],now_iso()))
            except aiosqlite.IntegrityError: await db.rollback(); return False,"duplicate"
            await db.execute("INSERT INTO balances(user_id,steel,aluminum,rubber,metalscrap,iron,plastic,copper,glass,admin_adjustment,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET steel=steel+excluded.steel,aluminum=aluminum+excluded.aluminum,rubber=rubber+excluded.rubber,metalscrap=metalscrap+excluded.metalscrap,iron=iron+excluded.iron,plastic=plastic+excluded.plastic,copper=copper+excluded.copper,glass=glass+excluded.glass,updated_at=excluded.updated_at",
                (uid,res["steel"],res["aluminum"],res["rubber"],res["metalscrap"],res["iron"],res["plastic"],res["copper"],res["glass"],0,now_iso()))
            await db.commit(); return True,"ok"
        finally: await db.close()

    async def get_balance(self,uid):
        db=await self.connect()
        try:
            cur=await db.execute("SELECT * FROM balances WHERE user_id=?",(uid,)); r=await cur.fetchone()
            return dict(r) if r else {"user_id":uid,**{k:0 for k in RESOURCE_NAMES},"admin_adjustment":0}
        finally: await db.close()
    async def get_balances(self):
        db=await self.connect()
        try:
            cur=await db.execute("SELECT * FROM balances"); rows=[dict(r) for r in await cur.fetchall()]; rows=[r for r in rows if total_for(r)!=0]; rows.sort(key=total_for,reverse=True); return rows
        finally: await db.close()
    async def adjust(self,eid,admin,uid,amount,resource=None):
        if resource and resource not in RESOURCE_NAMES: return False
        db=await self.connect()
        try:
            await db.execute("BEGIN IMMEDIATE")
            cur=await db.execute("SELECT value FROM settings WHERE key='active'"); active=(await cur.fetchone())["value"]=="1"
            if not active: await db.rollback(); return False
            if resource:
                await db.execute(f"INSERT INTO balances(user_id,{resource},updated_at) VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET {resource}={resource}+excluded.{resource},updated_at=excluded.updated_at",(uid,amount,now_iso()))
                action="resource_add"
            else:
                await db.execute("INSERT INTO balances(user_id,admin_adjustment,updated_at) VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET admin_adjustment=admin_adjustment+excluded.admin_adjustment,updated_at=excluded.updated_at",(uid,amount,now_iso())); action="bonus" if amount>=0 else "deduction"
            await db.execute("INSERT INTO audit_log(event_id,admin_id,target_user_id,action,resource,amount,created_at) VALUES(?,?,?,?,?,?,?)",(eid,admin,uid,action,resource,amount,now_iso()))
            await db.commit(); return True
        finally: await db.close()

    async def warehouse_locations(self,enabled_only=False):
        db=await self.connect()
        try:
            sql="SELECT * FROM warehouse_locations"+(" WHERE enabled=1" if enabled_only else "")+" ORDER BY sort_order,created_at,warehouse_id"
            cur=await db.execute(sql); return [dict(r) for r in await cur.fetchall()]
        finally: await db.close()

    async def warehouse_location(self,warehouse_id):
        db=await self.connect()
        try:
            cur=await db.execute("SELECT * FROM warehouse_locations WHERE warehouse_id=?",(warehouse_id,)); r=await cur.fetchone(); return dict(r) if r else None
        finally: await db.close()

    async def add_warehouse(self,warehouse_id,label,sort_order=0):
        db=await self.connect()
        try:
            await db.execute("INSERT INTO warehouse_locations(warehouse_id,label,enabled,sort_order,created_at) VALUES(?,?,1,?,?)",(warehouse_id,label.strip(),int(sort_order),now_iso()))
            await db.execute("INSERT OR IGNORE INTO warehouse_stock(warehouse_id,updated_at) VALUES(?,?)",(warehouse_id,now_iso()))
            await db.commit()
        finally: await db.close()

    async def update_warehouse(self,warehouse_id,label=None,enabled=None,sort_order=None):
        db=await self.connect()
        try:
            sets=[]; vals=[]
            if label is not None: sets.append("label=?"); vals.append(label.strip())
            if enabled is not None: sets.append("enabled=?"); vals.append(1 if enabled else 0)
            if sort_order is not None: sets.append("sort_order=?"); vals.append(int(sort_order))
            if sets:
                vals.append(warehouse_id); await db.execute(f"UPDATE warehouse_locations SET {','.join(sets)} WHERE warehouse_id=?",tuple(vals)); await db.commit()
        finally: await db.close()

    async def delete_warehouse(self,warehouse_id):
        db=await self.connect()
        try:
            await db.execute("DELETE FROM warehouse_locations WHERE warehouse_id=?",(warehouse_id,)); await db.commit()
        finally: await db.close()

    async def warehouse_stock(self,warehouse_id):
        db=await self.connect()
        try:
            cur=await db.execute("SELECT * FROM warehouse_stock WHERE warehouse_id=?",(warehouse_id,)); r=await cur.fetchone()
            return dict(r) if r else {"warehouse_id":warehouse_id,**{k:0 for k in RESOURCE_NAMES},"updated_by":None,"updated_at":""}
        finally: await db.close()

    async def replace_warehouse_stock(self,warehouse_id,res,updated_by):
        db=await self.connect()
        try:
            await db.execute("""INSERT INTO warehouse_stock(warehouse_id,steel,aluminum,rubber,metalscrap,iron,plastic,copper,glass,updated_by,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(warehouse_id) DO UPDATE SET steel=excluded.steel,aluminum=excluded.aluminum,rubber=excluded.rubber,
                metalscrap=excluded.metalscrap,iron=excluded.iron,plastic=excluded.plastic,copper=excluded.copper,glass=excluded.glass,
                updated_by=excluded.updated_by,updated_at=excluded.updated_at""",
                (warehouse_id,res["steel"],res["aluminum"],res["rubber"],res["metalscrap"],res["iron"],res["plastic"],res["copper"],res["glass"],updated_by,now_iso()))
            await db.commit()
        finally: await db.close()

    async def ticket_types(self,enabled_only=False):
        db=await self.connect()
        try:
            sql="SELECT * FROM ticket_types"+(" WHERE enabled=1" if enabled_only else "")+" ORDER BY sort_order,type_id"; cur=await db.execute(sql); return [dict(r) for r in await cur.fetchall()]
        finally: await db.close()
    async def ticket_type(self,type_id):
        db=await self.connect()
        try: cur=await db.execute("SELECT * FROM ticket_types WHERE type_id=?",(type_id,)); r=await cur.fetchone(); return dict(r) if r else None
        finally: await db.close()
    async def save_ticket_type(self,d):
        db=await self.connect()
        try:
            await db.execute("INSERT INTO ticket_types(type_id,label,description,emoji,category_id,staff_role_ids,welcome_message,questions,enabled,sort_order) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(type_id) DO UPDATE SET label=excluded.label,description=excluded.description,emoji=excluded.emoji,category_id=excluded.category_id,staff_role_ids=excluded.staff_role_ids,welcome_message=excluded.welcome_message,questions=excluded.questions,enabled=excluded.enabled,sort_order=excluded.sort_order",
                (d["type_id"],d["label"],d.get("description",""),d.get("emoji","🎫"),int(d.get("category_id",0) or 0),d.get("staff_role_ids","[]"),d.get("welcome_message",""),d.get("questions","[]"),int(d.get("enabled",1)),int(d.get("sort_order",0))))
            await db.commit()
        finally: await db.close()
    async def delete_ticket_type(self,type_id):
        db=await self.connect()
        try: await db.execute("DELETE FROM ticket_types WHERE type_id=?",(type_id,)); await db.commit()
        finally: await db.close()
    async def open_ticket(self,gid,uid,type_id):
        db=await self.connect()
        try: cur=await db.execute("SELECT * FROM tickets WHERE guild_id=? AND user_id=? AND type_id=? AND status='open' ORDER BY id DESC LIMIT 1",(gid,uid,type_id)); r=await cur.fetchone(); return dict(r) if r else None
        finally: await db.close()
    async def create_ticket(self,gid,cid,uid,type_id,answers):
        db=await self.connect()
        try: await db.execute("INSERT INTO tickets(guild_id,channel_id,user_id,type_id,answers,status,created_at) VALUES(?,?,?,?,?,'open',?)",(gid,cid,uid,type_id,json.dumps(answers,ensure_ascii=False),now_iso())); await db.commit()
        finally: await db.close()
    async def ticket_by_channel(self,cid):
        db=await self.connect()
        try: cur=await db.execute("SELECT * FROM tickets WHERE channel_id=?",(cid,)); r=await cur.fetchone(); return dict(r) if r else None
        finally: await db.close()
    async def close_ticket(self,cid,admin):
        db=await self.connect()
        try: await db.execute("UPDATE tickets SET status='closed',closed_at=?,closed_by=? WHERE channel_id=?",(now_iso(),admin,cid)); await db.commit()
        finally: await db.close()

    async def attendance_login(self,uid):
        db=await self.connect()
        try:
            await db.execute("BEGIN IMMEDIATE"); cur=await db.execute("SELECT state FROM attendance_sessions WHERE user_id=?",(uid,)); r=await cur.fetchone()
            if r: await db.rollback(); return False,r["state"]
            n=now_iso(); await db.execute("INSERT INTO attendance_sessions(user_id,state,login_at,break_started_at,break_seconds,updated_at) VALUES(?,'active',?,NULL,0,?)",(uid,n,n)); await db.execute("INSERT INTO attendance_log(user_id,action,actor_id,seconds,created_at) VALUES(?,'login',?,0,?)",(uid,uid,n)); await db.commit(); return True,"active"
        finally: await db.close()
    async def attendance_break(self,uid):
        db=await self.connect()
        try:
            await db.execute("BEGIN IMMEDIATE"); cur=await db.execute("SELECT * FROM attendance_sessions WHERE user_id=?",(uid,)); r=await cur.fetchone()
            if not r: await db.rollback(); return False,"offline"
            n=datetime.now(timezone.utc); ns=n.isoformat(timespec="seconds")
            if r["state"]=="active": await db.execute("UPDATE attendance_sessions SET state='break',break_started_at=?,updated_at=? WHERE user_id=?",(ns,ns,uid)); state="break"; action="break_start"
            else:
                started=datetime.fromisoformat(r["break_started_at"]) if r["break_started_at"] else n; added=max(0,int((n-started).total_seconds())); await db.execute("UPDATE attendance_sessions SET state='active',break_started_at=NULL,break_seconds=break_seconds+?,updated_at=? WHERE user_id=?",(added,ns,uid)); state="active"; action="break_end"
            await db.execute("INSERT INTO attendance_log(user_id,action,actor_id,seconds,created_at) VALUES(?,?,?,0,?)",(uid,action,uid,ns)); await db.commit(); return True,state
        finally: await db.close()
    async def attendance_logout(self,uid,actor=None,forced=False):
        db=await self.connect()
        try:
            await db.execute("BEGIN IMMEDIATE"); cur=await db.execute("SELECT * FROM attendance_sessions WHERE user_id=?",(uid,)); r=await cur.fetchone()
            if not r: await db.rollback(); return False,0
            n=datetime.now(timezone.utc); worked=max(0,int((n-datetime.fromisoformat(r["login_at"])).total_seconds())-int(r["break_seconds"] or 0))
            if r["state"]=="break" and r["break_started_at"]: worked=max(0,worked-max(0,int((n-datetime.fromisoformat(r["break_started_at"])).total_seconds())))
            ns=n.isoformat(timespec="seconds"); await db.execute("INSERT INTO attendance_totals(user_id,total_seconds,updated_at) VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET total_seconds=total_seconds+excluded.total_seconds,updated_at=excluded.updated_at",(uid,worked,ns)); await db.execute("DELETE FROM attendance_sessions WHERE user_id=?",(uid,)); await db.execute("INSERT INTO attendance_log(user_id,action,actor_id,seconds,created_at) VALUES(?,?,?,?,?)",(uid,"force_logout" if forced else "logout",actor or uid,worked,ns)); await db.commit(); return True,worked
        finally: await db.close()
    async def sessions(self):
        db=await self.connect()
        try: cur=await db.execute("SELECT * FROM attendance_sessions ORDER BY login_at"); return [dict(r) for r in await cur.fetchall()]
        finally: await db.close()
    async def total_seconds(self,uid,include_live=True):
        db=await self.connect()
        try:
            cur=await db.execute("SELECT total_seconds FROM attendance_totals WHERE user_id=?",(uid,)); r=await cur.fetchone(); total=int(r["total_seconds"] or 0) if r else 0
            if include_live:
                cur=await db.execute("SELECT * FROM attendance_sessions WHERE user_id=?",(uid,)); s=await cur.fetchone()
                if s:
                    n=datetime.now(timezone.utc); live=max(0,int((n-datetime.fromisoformat(s["login_at"])).total_seconds())-int(s["break_seconds"] or 0))
                    if s["state"]=="break" and s["break_started_at"]: live=max(0,live-max(0,int((n-datetime.fromisoformat(s["break_started_at"])).total_seconds())))
                    total+=live
            return total
        finally: await db.close()
    async def set_note(self,uid,note,admin):
        db=await self.connect(); note=(note or "").strip()
        try:
            if note: await db.execute("INSERT INTO staff_notes(user_id,note,updated_by,updated_at) VALUES(?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET note=excluded.note,updated_by=excluded.updated_by,updated_at=excluded.updated_at",(uid,note,admin,now_iso()))
            else: await db.execute("DELETE FROM staff_notes WHERE user_id=?",(uid,))
            await db.commit()
        finally: await db.close()
    async def notes(self):
        db=await self.connect()
        try: cur=await db.execute("SELECT user_id,note FROM staff_notes"); return {int(r["user_id"]):r["note"] for r in await cur.fetchall()}
        finally: await db.close()

    async def reset_attendance(self):
        """Reset current attendance sessions and accumulated hours for this server database."""
        db=await self.connect()
        try:
            await db.execute("BEGIN IMMEDIATE")
            await db.execute("DELETE FROM attendance_sessions")
            await db.execute("DELETE FROM attendance_totals")
            await db.commit()
        finally: await db.close()

    async def add_workshop_entry(self,uid,service,modification_type='',invoice_filename='',car_filename=''):
        db=await self.connect()
        try:
            await db.execute(
                "INSERT INTO workshop_entries(user_id,service,modification_type,invoice_filename,car_filename,created_at) VALUES(?,?,?,?,?,?)",
                (int(uid),str(service),str(modification_type or ''),str(invoice_filename or ''),str(car_filename or ''),now_iso())
            )
            await db.commit()
        finally: await db.close()

    async def workshop_leaderboard(self,limit=25):
        db=await self.connect()
        try:
            cur=await db.execute(
                "SELECT user_id,COUNT(*) AS total FROM workshop_entries GROUP BY user_id ORDER BY total DESC,user_id LIMIT ?",
                (int(limit),)
            )
            return [dict(r) for r in await cur.fetchall()]
        finally: await db.close()

    async def reset_workshops(self):
        db=await self.connect()
        try:
            await db.execute("DELETE FROM workshop_entries")
            await db.commit()
        finally: await db.close()

    async def get_meta(self,key,default=''):
        db=await self.connect()
        try:
            cur=await db.execute("SELECT value FROM bot_meta WHERE key=?",(str(key),));r=await cur.fetchone()
            return r['value'] if r else default
        finally: await db.close()

    async def set_meta(self,key,value):
        db=await self.connect()
        try:
            await db.execute("INSERT INTO bot_meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(str(key),str(value)))
            await db.commit()
        finally: await db.close()

