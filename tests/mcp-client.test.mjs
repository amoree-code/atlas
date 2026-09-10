import assert from "node:assert/strict";
import test from "node:test";
import { McpClient } from "../dist/infrastructure/mcp/mcp-client.js";
import { mkdtemp, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";

test("discovers, filters, and approval-gates MCP tools", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "atlas-mcp-"));
  const server = path.join(root, "server.mjs");
  await writeFile(server, `let b=Buffer.alloc(0); process.stdin.on('data',c=>{b=Buffer.concat([b,c]); while(1){let h=b.indexOf('\\r\\n\\r\\n');if(h<0)return;let n=+(b.subarray(0,h).toString().match(/\\d+/)?.[0]??0),s=h+4;if(b.length<s+n)return;let q=JSON.parse(b.subarray(s,s+n));b=b.subarray(s+n);let r=q.method==='tools/list'?{tools:[{name:'read',annotations:{readOnlyHint:true}},{name:'write',annotations:{readOnlyHint:false}}]}:q.method==='tools/call'?{ok:true}:{};let x=Buffer.from(JSON.stringify({jsonrpc:'2.0',id:q.id,result:r}));process.stdout.write('Content-Length: '+x.length+'\\r\\n\\r\\n');process.stdout.write(x);}}); setTimeout(()=>process.exit(0), 1000);`);
  const client = new McpClient({ command: process.execPath, args: [server], cwd: root, allowedTools: ["read", "write"] });
  try {
    await client.connect();
    assert.deepEqual((await client.listTools()).map((tool) => tool.name), ["read", "write"]);
    await assert.rejects(() => client.callTool("write"), /requires explicit approval/);
    assert.deepEqual(await client.callTool("write", {}, true), { ok: true });
  } catch (error) { console.error(error); throw error; } finally { client.close(); }
});
