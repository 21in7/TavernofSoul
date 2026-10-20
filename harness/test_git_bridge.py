"""Node fake capabilities exercise the same module evaluated in functions.exec.

Synthetic timings assert sequencing only; they are not PR performance evidence.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess

from harness import git_publish as native, git_transport as transport
from harness.test_git_publish import (prepared, isolated_storage_environment,
                                      to_pr, pr_data, rows_for, check_response)


NODE_TESTS = r'''
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const B = require(process.argv[1]);
const RUN = '123456-abcdef', ID = '1'.repeat(64), NEXT = '2'.repeat(64);
const FETCH = B.allowlist[0], WRITE = B.allowlist[1];
const hash = raw => crypto.createHash('sha256').update(raw).digest('hex');
const job = (id=ID, tool=FETCH, args={url:'fixture'}) => ({request_id:id, tool, arguments:args});
const pending = (request=job(), poll=0, gh={}) => ({run_id:RUN, github:{status:'awaiting_connector', ...gh}, request, poll_after_seconds:poll});
const done = (gh={}) => pending(null, 0, {status:'merged', step:'done', cleanup:{status:'complete'}, ...gh});
const ready = () => ({run_id:RUN, status:'awaiting_github', simulated:false,
  changed_files:['fixture.py'], github:{status:'awaiting_connector',step:'repository'},
  current:{time:'2026-10-20T01:00:00+00:00'}});
const cases = [];
async function test(name, fn) { await fn(); cases.push(name); }

function fixture(sequence, options={}) {
  let saved, active, number=0, stamp=1000;
  const calls=[], notifications=[], waits=[], artifacts=[], chunks=new Map();
  const clone = x => x === undefined ? undefined : JSON.parse(JSON.stringify(x));
  const make = (item, overrides={}) => {
    const native = item.native || item;
    const code = item.code === undefined ? 0 : item.code;
    const raw = Buffer.from(JSON.stringify(native)+'\n');
    const op = (++number).toString(16).padStart(64,'0');
    const env = {version:'git-transport-v1', operation_id:op, bytes:raw.length, sha256:hash(raw), native_exit_code:code,
      started_at:1, ended_at:2};
    if (raw.length <= 32768) env.inline = raw.toString('utf8');
    else {
      env.chunks={bytes:12288,count:Math.ceil(raw.length/12288),encoding:'base64'};
      chunks.set(op,raw);
    }
    Object.assign(env,overrides);
    if (options.mutateEnvelope) options.mutateEnvelope(env);
    return {output:JSON.stringify(env),exit_code:code,original_token_count:100};
  };
  const take = () => { assert(sequence.length, 'unexpected request/retry'); return make(sequence.shift()); };
  const tools={
    exec_command:async args => {
      calls.push({kind:'shell',args});
      assert(!args.cmd.includes('fixture secret'), 'raw arguments entered shell');
      if (args.cmd.includes("'chunk'")) {
        const op=args.cmd.match(/'--operation-id' '([a-f0-9]+)'/)[1];
        const index=Number(args.cmd.match(/'--index' '([0-9]+)'/)[1]);
        const raw=chunks.get(op), part=raw.subarray(index*12288,(index+1)*12288);
        const result={version:'git-transport-v1',operation_id:op,index,offset:index*12288,
          total_bytes:raw.length,bytes:part.length,sha256:hash(raw),data:part.toString('base64')};
        if (options.mutateChunk) options.mutateChunk(result);
        return {output:JSON.stringify(result),exit_code:0};
      }
      if (args.cmd.includes("'accept'")) {
        assert(args.tty === true && args.cmd.startsWith('stty -echo && exec '));
        assert(!args.cmd.includes('structuredContent'));
        active={cmd:args.cmd,frame:''};
        return {output:'transport-input-ready-v1\r\n',session_id:99};
      }
      assert(args.cmd.includes("'request'"));
      return take();
    },
    write_stdin:async args => {
      calls.push({kind:'stdin',args:{session_id:args.session_id}});
      assert(args.yield_time_ms<=30000);
      if (args.session_id===42) {
        assert(!args.chars);
        return {output:JSON.stringify(options.summary || ready(),null,2)+'\n',exit_code:0};
      }
      assert(active && args.session_id===99);
      active.frame += args.chars || '';
      if (!active.frame.endsWith('\n.\n')) return {output:'',session_id:99};
      const frame=active.frame.slice(0,-2).replace(/\s/g,'');
      const response=JSON.parse(Buffer.from(frame,'base64').toString('utf8'));
      const id=active.cmd.match(/'--request-id' '([a-f0-9]+)'/)[1];
      assert(saved.operations[id], 'ID must be stored before dispatch');
      assert.equal(saved.operations[id].phase,'responded');
      calls.push({kind:'accept',id,response});
      active=null;
      return take();
    }
  };
  for (const name of B.allowlist) tools[name]=async args => {
    assert(saved, 'private state must exist');
    const ids=Object.keys(saved.operations), id=ids[ids.length-1];
    assert.equal(saved.operations[id].phase,'dispatching');
    calls.push({kind:'connector',tool:name,args:clone(args)});
    if (options.connector) return options.connector(args,name);
    return {structuredContent:{fixture:'fixture secret',created_at:'2026-10-20T01:00:01Z'}};
  };
  const cap={tools,load:async()=>clone(saved),store:async(k,v)=>{saved=clone(v);},
    notify:async value=>{assert.deepEqual(Object.keys(value),['stage']); notifications.push(value);},
    attachArtifact:async url=>{calls.push({kind:'attach'}); artifacts.push(url);},
    sleep:async ms=>{waits.push(ms); stamp+=ms;},yield:async()=>{calls.push({kind:'yield'});},now:()=>++stamp};
  return {cap,calls,notifications,waits,artifacts,get saved(){return saved;}, make,
    bridge:()=>B.create(cap), shells:()=>calls.filter(x=>x.kind==='shell'),
    accepts:()=>calls.filter(x=>x.kind==='accept'), connectors:()=>calls.filter(x=>x.kind==='connector')};
}
const mode={readOnly:false,demo:false,git:true};
(async()=>{
  await test('portable bytes and SHA agree with independent Node implementation',async()=>{
    for (const text of ['', 'abc','한글 🐈', 'x'.repeat(17000)]) {
      assert.deepEqual(B.utf8(text),Array.from(Buffer.from(text)));
      assert.equal(B.sha256(B.utf8(text)),hash(Buffer.from(text)));
      assert.equal(B.base64(B.utf8(text)),Buffer.from(text).toString('base64'));
    }
  });
  await test('workflow completion immediately starts request without sleep',async()=>{
    const f=fixture([pending(),done()]);
    const result=await f.bridge().handoff({session_id:42,output:'[8/8 github] waiting\n'},mode);
    assert.equal(result.native.github.step,'done');
    assert.equal(f.waits.length,0);
    assert.equal(f.calls.filter(x=>x.kind==='shell').length,2);
    const first=f.calls.findIndex(x=>x.kind==='shell');
    assert.equal(f.calls.slice(0,first).filter(x=>x.kind==='stdin').length,1);
    assert(f.saved.events.some(x=>x.kind==='workflow_ready'));
    assert(f.saved.events.some(x=>x.kind==='bridge_start'));
  });
  await test('ordinary accept uses exactly one shell and exact args',async()=>{
    const args={repository_full_name:'owner/repo',tree:[{content:'fixture secret $(never) `never` 한글'}]};
    const f=fixture([pending(job(ID,WRITE,args)),pending(job(NEXT)),done()]);
    await f.bridge().publish(RUN);
    assert.deepEqual(f.connectors()[0].args,args);
    assert.equal(f.shells().length,3); assert.equal(f.accepts().length,2);
    assert.equal(f.saved.operations[ID].phase,'accepted');
    assert.equal(f.saved.operations[ID].response.structuredContent.fixture,'fixture secret');
    assert(f.saved.events.some(x=>x.kind==='connector_response' && x.duration_ms>=0));
  });
  await test('complete inline diagnostic quotations reach connector as exact arguments',async()=>{
    for (const phrase of ['Warning: truncated output','tokens truncated','Output truncated']) {
      const args={body:'Documentation legitimately quotes '+phrase};
      const f=fixture([pending(job(ID,WRITE,args)),done()]);
      const result=await f.bridge().publish(RUN);
      assert.deepEqual(f.connectors(),[{kind:'connector',tool:WRITE,args}]);
      assert.deepEqual(f.saved.operations[ID].arguments,args);
      assert.equal(f.accepts()[0].id,ID);
      assert.equal(f.shells().length,2);
      assert.equal(result.native.github.step,'done');
    }
  });
  await test('duplicate write ID is refused without dispatch',async()=>{
    const f=fixture([pending(job(ID,WRITE)),pending(job(ID,WRITE))]);
    await assert.rejects(f.bridge().publish(RUN),/duplicate_dispatch/);
    assert.equal(f.connectors().length,1); assert.equal(f.accepts().length,1);
    await assert.rejects(f.bridge().publish(RUN),/existing_state/);
    assert.equal(f.connectors().length,1);
  });
  await test('connector exception is accepted on same ID then native failure preserved',async()=>{
    const f=fixture([pending(job(ID,WRITE)),{native:pending(null,0,{status:'needs_reconciliation'}),code:1}],
      {connector:async()=>{throw new Error('private failure');}});
    const result=await f.bridge().publish(RUN);
    assert.equal(result.exitCode,1); assert.equal(result.native.github.status,'needs_reconciliation');
    assert.equal(f.accepts()[0].id,ID); assert.equal(f.accepts()[0].response.isError,true);
    assert.equal(f.connectors().length,1);
  });
  await test('poll waits in at most 30 second steps with yields',async()=>{
    const f=fixture([pending(job(),65),done()]);
    await f.bridge().publish(RUN);
    assert.deepEqual(f.waits,[30000,30000,5000]);
  });
  await test('negative workflow modes and states cannot publish',async()=>{
    for (const bad of [{...mode,readOnly:true},{...mode,demo:true},{...mode,git:false},{}]) {
      const f=fixture([]);
      await assert.rejects(f.bridge().handoff({output:JSON.stringify(ready()),exit_code:0},bad));
      assert.equal(f.shells().length,0);
    }
    for (const changed of [{status:'failed'},{status:'passed'},{status:'demonstrated'},
      {simulated:true},{read_only:true},{no_git:true},{github_enabled:false},{changed_files:[]},
      {github:{status:'skipped'}},{archive:{status:'pending'}},{run_id:'invalid'}]) {
      const f=fixture([]);
      await assert.rejects(f.bridge().handoff({output:JSON.stringify({...ready(),...changed}),exit_code:0},mode));
      assert.equal(f.shells().length,0);
    }
    for (const output of ['no summary','{"status":','{}','{"status":"awaiting_github"}\ntrailing']) {
      const f=fixture([]);
      await assert.rejects(f.bridge().handoff({output,exit_code:0},mode)); assert.equal(f.shells().length,0);
    }
    const f=fixture([]);
    await assert.rejects(f.bridge().handoff({output:JSON.stringify(ready()),exit_code:1},mode));
    assert.equal(f.shells().length,0);
  });
  await test('PR attached immediately after verified observation before next connector',async()=>{
    const url='https://github.com/owner/repo/pull/7';
    const f=fixture([pending(job(ID,'mcp__codex_apps__github_create_pull_request')),
      pending(job(NEXT),0,{pr_url:url,pr_number:7}),done({pr_url:url,pr_number:7})]);
    await f.bridge().publish(RUN);
    assert.deepEqual(f.artifacts,[url]);
    const attach=f.calls.findIndex(x=>x.kind==='attach');
    const con=f.calls.map((x,i)=>x.kind==='connector'?i:-1).filter(x=>x>=0);
    assert(attach>con[0] && attach<con[1]);
    assert(f.saved.events.some(x=>x.kind==='pr_observed'));
  });
  await test('ordinary 17KiB create_tree stays in a single inline read',async()=>{
    const f=fixture([pending(job(ID,WRITE,{tree:[{content:'x'.repeat(17000)}]})),done()]);
    await f.bridge().publish(RUN);
    assert.equal(f.shells().length,2); assert.equal(f.accepts().length,1);
  });
  await test('large UTF8 output is reconstructed with exact bounded chunks',async()=>{
    const content='한글 🐈'.repeat(10000);
    const f=fixture([pending(job(ID,WRITE,{content})),done()]);
    await f.bridge().publish(RUN);
    assert.equal(f.connectors()[0].args.content,content);
    assert(f.shells().filter(x=>x.args.cmd.includes("'chunk'")).length>1);
    assert.equal(f.accepts().length,1);
  });
  await test('oversized response uses stdin without OS argument size limit',async()=>{
    const response={structuredContent:{text:'한글'.repeat(40000)}};
    const f=fixture([pending(),done()],{connector:async()=>response});
    await f.bridge().publish(RUN);
    assert.deepEqual(f.accepts()[0].response,response);
    assert.equal(f.shells().length,2);
    assert(f.shells().every(x=>x.args.cmd.length<1000));
  });
  await test('chunk hash size and metadata corruption never dispatches',async()=>{
    for (const mutateChunk of [c=>{c.offset++;},c=>{c.bytes--;},c=>{c.sha256='0'.repeat(64);},
      c=>{c.data=c.data.slice(4);},c=>{c.data='AAAA'+c.data.slice(4);}]) {
      const f=fixture([pending(job(ID,WRITE,{content:'x'.repeat(40000)}))],{mutateChunk});
      await assert.rejects(f.bridge().publish(RUN)); assert.equal(f.connectors().length,0);
      assert.equal(f.shells().filter(x=>x.args.cmd.includes("'request'")).length,1);
    }
  });
  await test('inline truncation and hash failures are never new request retries',async()=>{
    for (const mutateEnvelope of [e=>{e.inline=e.inline.slice(0,-2);},e=>{e.sha256='0'.repeat(64);},
      e=>{e.bytes++;},e=>{e.native_exit_code=1;},e=>{
        e.inline='{"request":'; e.bytes=Buffer.byteLength(e.inline); e.sha256=hash(Buffer.from(e.inline));
      }]) {
      const f=fixture([pending()],{mutateEnvelope});
      await assert.rejects(f.bridge().publish(RUN));
      assert.equal(f.shells().length,1); assert.equal(f.connectors().length,0);
    }
  });
  await test('wrapper truncation error and token budget metadata refuse complete payloads',async()=>{
    for (const metadata of [{truncated:true},{output_truncated:true},{isError:true},
      {original_token_count:22001},{original_token_count:-1},{original_token_count:'100'}]) {
      const f=fixture([pending()]);
      const exec=f.cap.tools.exec_command;
      f.cap.tools.exec_command=async args=>({...await exec(args),...metadata});
      await assert.rejects(f.bridge().publish(RUN),/tool_output_truncated/);
      assert.equal(f.shells().length,1); assert.equal(f.connectors().length,0);
      assert.equal(f.accepts().length,0);
    }
    const f=fixture([]);
    await assert.rejects(f.bridge().handoff({output:JSON.stringify(ready()),exit_code:0,
      original_token_count:16001},mode),/tool_output_truncated/);
    assert.equal(f.shells().length,0);
  });
  await test('incomplete nonJSON and extra output framing refuse dispatch without retries',async()=>{
    for (const corrupt of [text=>text.slice(0,-1),text=>'Warning: truncated output\n'+text,
      text=>text+'\n{}',text=>text+'\nOutput truncated']) {
      const f=fixture([pending()]);
      const exec=f.cap.tools.exec_command;
      f.cap.tools.exec_command=async args=>{
        const result=await exec(args); return {...result,output:corrupt(result.output)};
      };
      await assert.rejects(f.bridge().publish(RUN),/invalid_json_or_truncation/);
      assert.equal(f.shells().length,1); assert.equal(f.connectors().length,0);
      assert.equal(f.accepts().length,0);
    }
  });
  await test('allowlist and missing tool checked before dispatch',async()=>{
    for (const tool of ['mcp__codex_apps__github_delete_branch','shell']) {
      const f=fixture([pending(job(ID,tool))]);
      await assert.rejects(f.bridge().publish(RUN),/request_tool_invalid/); assert.equal(f.connectors().length,0);
    }
    const f=fixture([pending()]); delete f.cap.tools[FETCH];
    await assert.rejects(f.bridge().publish(RUN),/request_tool_invalid/);
  });
  await test('native required gate failures and awaiting_ci remain explicit',async()=>{
    for (const status of ['failed','needs_reconciliation','awaiting_ci','cleanup_pending']) {
      const native=pending(null,0,{status,error:'required CI not proven',checks:{required:'pending'}});
      const f=fixture([{native,code:status==='awaiting_ci'?0:1}]);
      const result=await f.bridge().publish(RUN);
      assert.deepEqual(result.native,native); assert.equal(f.connectors().length,0);
    }
  });
  await test('intermediate merged cleanup proof continues and archive pending remains nonzero',async()=>{
    const end=done(); end.archive={status:'pending'};
    const f=fixture([{native:pending(job(),0,{status:'merged',step:'cleanup_pr'}),code:1},
      {native:pending(job(NEXT),0,{status:'merged',step:'cleanup_repository'}),code:1},{native:end,code:1}]);
    const result=await f.bridge().publish(RUN);
    assert.equal(f.connectors().length,2); assert.equal(result.exitCode,1);
    assert.equal(result.native.archive.status,'pending');
  });
  await test('unknown dispatch is saved before failed accept and never automatically redispatched',async()=>{
    const f=fixture([pending(job(ID,WRITE))]);
    const exec=f.cap.tools.exec_command;
    f.cap.tools.exec_command=async args=>{
      if(args.cmd.includes("'accept'")) throw new Error('interrupted shell');
      return exec(args);
    };
    await assert.rejects(f.bridge().publish(RUN));
    assert.equal(f.saved.operations[ID].phase,'responded');
    assert(f.saved.operations[ID].response);
    await assert.rejects(f.bridge().publish(RUN),/existing_state/);
    assert.equal(f.connectors().length,1);
  });
  if (process.argv[2]) await test('actual native CI gate result remains authoritative through bridge',async()=>{
    const item=JSON.parse(process.argv[2]);
    const f=fixture([item]);
    const result=await f.bridge().publish(RUN);
    assert.deepEqual(result.native,item.native);
    assert.equal(result.exitCode,item.code);
    assert.equal(f.connectors().length,0);
  });
  process.stdout.write(JSON.stringify({cases:cases.length,passed:cases.length,names:cases}));
})().catch(error=>{process.stderr.write(error.stack);process.exitCode=1;});
'''


def test_parent_bridge_fake_tools_contract():
    node = shutil.which('node')
    assert node, 'Node.js >= 18 is required by the harness; missing Node is a failure.'
    module = Path(__file__).with_name('git_bridge.js')
    result = subprocess.run([node, '-e', NODE_TESTS, str(module)],
                            env={'PATH': os.defpath}, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report['cases'] == report['passed'] == 20


def test_bridge_preserves_actual_native_ci_failure(prepared):
    ledger = prepared['ledger']
    to_pr(ledger)
    native.accept(ledger, pr_data(ledger))
    native.save(prepared['directory'], ledger)
    first = json.loads(transport.transact('request', ledger['run_id'])['inline'])
    rows = rows_for(ledger)
    rows[0]['conclusion'] = 'failure'
    result = transport.transact('accept', ledger['run_id'], first['request']['request_id'],
                                transport.encode(check_response(rows)))
    actual = {'native': json.loads(result['inline']), 'code': result['native_exit_code']}
    assert actual['code'] == 1 and actual['native']['github']['status'] == 'failed'
    node = shutil.which('node')
    assert node, 'Node.js >= 18 is required by the harness.'
    script = Path(__file__).with_name('git_bridge.js')
    process = subprocess.run([node, '-e', NODE_TESTS, str(script), json.dumps(actual)],
                             env={'PATH': os.defpath}, capture_output=True, text=True, timeout=60)
    assert process.returncode == 0, process.stdout + process.stderr
    report = json.loads(process.stdout)
    assert report['cases'] == report['passed'] == 21
