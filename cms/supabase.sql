-- Run once in Supabase SQL Editor. Safe to rerun; no existing data is deleted.
create table if not exists public.ytloop_control (
  id integer primary key check (id = 1),
  config jsonb not null default '{}'::jsonb,
  revision bigint not null default 0,
  snapshot jsonb not null default '{}'::jsonb,
  agent_id uuid,
  last_seen timestamptz,
  updated_at timestamptz not null default now()
);
insert into public.ytloop_control(id) values (1) on conflict do nothing;
create table if not exists public.ytloop_commands (
  id uuid primary key,
  seq bigint generated always as identity unique,
  action text not null check (action in ('configure','start','pause','next','reset','end_live','refresh')),
  payload jsonb not null default '{}'::jsonb,
  status text not null default 'pending' check (status in ('pending','delivered','done','error','cancelled','expired')),
  created_at timestamptz not null default now(),
  expires_at timestamptz,
  delivered_to uuid,
  result jsonb
);
create index if not exists ytloop_command_status on public.ytloop_commands(status,seq);
create table if not exists public.ytloop_auth_limits (
  key text primary key,
  window_start timestamptz not null default now(),
  attempts integer not null default 0
);
alter table public.ytloop_control enable row level security;
alter table public.ytloop_commands enable row level security;
alter table public.ytloop_auth_limits enable row level security;
-- No anon/authenticated policies: only the backend's service role may access these.
revoke all on public.ytloop_control, public.ytloop_commands, public.ytloop_auth_limits from anon, authenticated;
grant all on public.ytloop_control, public.ytloop_commands, public.ytloop_auth_limits to service_role;
grant usage, select on sequence public.ytloop_commands_seq_seq to service_role;

create or replace function public.ytloop_login_gate(p_key text)
returns jsonb language plpgsql security definer set search_path = public as $$
declare entry public.ytloop_auth_limits%rowtype;
begin
  insert into public.ytloop_auth_limits(key) values (p_key) on conflict do nothing;
  select * into entry from public.ytloop_auth_limits where key=p_key for update;
  if entry.window_start < now() - interval '15 minutes' then
    update public.ytloop_auth_limits set attempts=1,window_start=now() where key=p_key;
  elsif entry.attempts >= 8 then
    raise exception 'LOGIN_LIMIT';
  else
    update public.ytloop_auth_limits set attempts=attempts+1 where key=p_key;
  end if;
  delete from public.ytloop_auth_limits where window_start < now() - interval '2 days';
  return '{"ok":true}'::jsonb;
end $$;

create or replace function public.ytloop_enqueue(p_action text,p_payload jsonb,p_request uuid)
returns jsonb language plpgsql security definer set search_path = public as $$
declare ctl public.ytloop_control%rowtype; existing public.ytloop_commands%rowtype;
        body jsonb; expiry timestamptz;
begin
  select * into ctl from public.ytloop_control where id=1 for update;
  select * into existing from public.ytloop_commands where id=p_request;
  if found then
    return jsonb_build_object('id',existing.id,'status',existing.status,'duplicate',true);
  end if;
  if p_action not in ('configure','start','pause','next','reset','end_live','refresh') then raise exception 'INVALID_ACTION'; end if;
  if p_action in ('start','next','end_live','reset') and
    (ctl.last_seen is null or ctl.last_seen < now()-interval '60 seconds') then raise exception 'AGENT_OFFLINE'; end if;
  if p_action in ('configure','reset') and coalesce((ctl.snapshot#>>'{state,running}')::boolean,false) then raise exception 'PAUSE_FIRST'; end if;
  if p_action in ('start','next','reset') and coalesce(ctl.config->>'video_id','')='' then raise exception 'NO_CONFIG'; end if;
  if p_action='end_live' and coalesce(p_payload->>'confirmation','') <> coalesce(ctl.snapshot#>>'{state,video_id}','') then raise exception 'STOP_MISMATCH'; end if;
  if p_action in ('pause','end_live') then
    update public.ytloop_commands set status='cancelled',result='{"message":"Dibatalkan oleh perintah stop/pause yang lebih baru."}'::jsonb
      where status='pending' and action in ('start','next','reset');
  end if;
  if p_action='configure' then
    update public.ytloop_commands set status='cancelled',result='{"message":"Diganti pengaturan yang lebih baru."}'::jsonb
      where status='pending' and action='configure';
    update public.ytloop_control set config=p_payload,revision=revision+1,updated_at=now() where id=1;
    body=p_payload;
  else
    body=p_payload || jsonb_build_object('_expected_video_id',case when p_action='end_live' then p_payload->>'confirmation' else ctl.config->>'video_id' end);
  end if;
  if (select count(*) from public.ytloop_commands where status in ('pending','delivered')) >= 50 then raise exception 'QUEUE_FULL'; end if;
  expiry=case when p_action in ('pause','configure','refresh') then null
              when p_action='end_live' then now()+interval '2 minutes'
              else now()+interval '15 minutes' end;
  insert into public.ytloop_commands(id,action,payload,expires_at) values(p_request,p_action,body,expiry);
  return jsonb_build_object('id',p_request,'status','pending','duplicate',false);
end $$;

create or replace function public.ytloop_sync(p_agent uuid,p_snapshot jsonb,p_receipts jsonb)
returns jsonb language plpgsql security definer set search_path = public as $$
declare ctl public.ytloop_control%rowtype; cmd public.ytloop_commands%rowtype; receipt jsonb;
begin
  select * into ctl from public.ytloop_control where id=1 for update;
  if ctl.agent_id is not null and ctl.agent_id<>p_agent then raise exception 'AGENT_CONFLICT'; end if;
  update public.ytloop_control set agent_id=p_agent,last_seen=now(),snapshot=p_snapshot,updated_at=now() where id=1;
  for receipt in select value from jsonb_array_elements(coalesce(p_receipts,'[]'::jsonb)) loop
    update public.ytloop_commands set status=case when (receipt->>'ok')::boolean then 'done' else 'error' end,result=receipt-'id'
      where id=(receipt->>'id')::uuid and status='delivered' and delivered_to=p_agent;
  end loop;
  update public.ytloop_commands set status='expired',result='{"message":"Perintah kedaluwarsa sebelum diterima RDP. Kirim lagi bila diperlukan."}'::jsonb
    where status='pending' and expires_at is not null and expires_at<now();
  select * into cmd from public.ytloop_commands where status in ('pending','delivered') order by seq limit 1;
  if found then
    update public.ytloop_commands set status='delivered',delivered_to=p_agent where id=cmd.id;
    return jsonb_build_object('command',jsonb_build_object('id',cmd.id,'action',cmd.action,'payload',cmd.payload),'server_time',extract(epoch from now()));
  end if;
  -- Bound history growth without deleting in-flight work or recently completed requests.
  delete from public.ytloop_commands where status not in ('pending','delivered') and created_at < now()-interval '30 days';
  return jsonb_build_object('command',null,'server_time',extract(epoch from now()));
end $$;

revoke all on function public.ytloop_login_gate(text),public.ytloop_enqueue(text,jsonb,uuid),public.ytloop_sync(uuid,jsonb,jsonb) from public,anon,authenticated;
grant execute on function public.ytloop_login_gate(text),public.ytloop_enqueue(text,jsonb,uuid),public.ytloop_sync(uuid,jsonb,jsonb) to service_role;
