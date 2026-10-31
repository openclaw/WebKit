// Flags: --expose-internals
'use strict';
const common = require('../common');
if (!common.hasCrypto)
  common.skip('missing crypto');

const assert = require('assert');
const { once } = require('events');
const net = require('net');
const tls = require('tls');
const fixtures = require('../common/fixtures');
const { hasMultiLocalhost } = require('../common/net');
const ca = fixtures.readKey('ca1-cert.pem');
const lookup = (_host, options, callback) => {
  callback(null, options.all ? [{ address: '127.0.0.1', family: 4 }] :
    '127.0.0.1', 4);
};
let cases = 0;

async function capture(port, version) {
  const client = tls.connect({
    host: 'agent1', port, lookup, ca, servername: 'agent1',
    minVersion: version, maxVersion: version,
  });
  const closed = new Promise((resolve) => client.once('close', resolve));
  const ticket = once(client, 'session');
  client.resume();
  try {
    const [, [session]] = await Promise.all([once(client, 'secureConnect'), ticket]);
    assert.strictEqual(client.authorized, true);
    assert.strictEqual(client.isSessionReused(), false);
    const raw = client._handle.getSession();
    assert(Buffer.isBuffer(session));
    assert(Buffer.isBuffer(raw));
    return { session, raw };
  } finally {
    client.destroy();
    await closed;
  }
}

async function direct(port, version, session, connected, options,
                      expectedReuse, label, setter = false) {
  const transport = net.connect({ host: 'agent1', port, lookup });
  let client;
  try {
    if (connected)
      await once(transport, 'connect');
    client = new tls.TLSSocket(transport, {
      ca, rejectUnauthorized: true,
      minVersion: version, maxVersion: version,
      ...options,
      ...(setter ? {} : { session }),
    });
    const closed = new Promise((resolve) => client.once('close', resolve));
    try {
      if (setter)
        client.setSession(session);
      // A direct TLSSocket caller owns handshake startup and peer verification.
      client.setServername('agent1');
      const secure = once(client, 'secure');
      client._start();
      client.resume();
      await secure;
      assert.strictEqual(client._handle.verifyError(), null);
      assert.strictEqual(
        tls.checkServerIdentity('agent1', client.getPeerCertificate()), undefined);
      const reused = client.isSessionReused();
      console.log('SESSION_CASE ' + JSON.stringify({
        label, version, connected, expectedReuse, reused,
      }));
      assert.strictEqual(reused, expectedReuse, label);
      cases++;
    } finally {
      client.destroy();
      await closed;
    }
  } finally {
    transport.destroy();
  }
}

async function testVersion(version) {
  const server = tls.createServer({
    key: fixtures.readKey('agent1-key.pem'),
    cert: fixtures.readKey('agent1-cert.pem'),
    minVersion: version, maxVersion: version,
  }, (socket) => socket.end('ok'));
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  try {
    const { port } = server.address();
    const { session, raw } = await capture(port, version);
    for (const connected of [true, false]) {
      for (const encoding of ['buffer', 'latin1']) {
        const encode = (value) => encoding === 'buffer' ? value :
          value.toString('latin1');
        const wrapped = encode(session);
        const label = `${version}/${encoding}/${connected ? 'connected' : 'connecting'}`;
        for (const [name, options, expected] of [
          ['explicit SNI', { servername: 'agent1' }, true],
          ['socket host', {}, true],
          ['positional socket', { socket: { _host: 'agent3' } }, true],
          ['explicit host', { host: 'agent1' }, true],
          ['SNI precedes host', { servername: 'agent1', host: 'agent3' }, true],
          ['foreign SNI', { servername: 'agent3' }, false],
          ['host precedes socket', { host: 'agent3' }, false],
        ]) {
          await direct(port, version, wrapped, connected, options,
                       expected, `${label}/${name}`);
        }
        await direct(port, version, wrapped, connected, {}, true,
                     `${label}/setSession`, true);
        await direct(port, version, encode(raw), connected,
                     { servername: 'agent1' }, false, `${label}/verified raw`);
        await direct(port, version, encode(raw), connected,
                     { servername: 'agent1', rejectUnauthorized: false },
                     true, `${label}/unverified raw`);
      }
    }
    if (hasMultiLocalhost()) {
      const client = tls.connect({
        host: 'agent1', port, ca, servername: 'agent1', session,
        minVersion: version, maxVersion: version,
        autoSelectFamily: true,
        lookup(_host, options, callback) {
          assert.strictEqual(options.all, true);
          callback(null, [
            { address: '127.0.0.2', family: 4 },
            { address: '127.0.0.1', family: 4 },
          ]);
        },
      });
      const closed = new Promise((resolve) => client.once('close', resolve));
      client.resume();
      try {
        await once(client, 'secureConnect');
        assert.strictEqual(client.authorized, true);
        assert.strictEqual(client.isSessionReused(), true);
        cases++;
        console.log('SESSION_FALLBACK ' + version);
      } finally {
        client.destroy();
        await closed;
      }
    }
  } finally {
    const closed = once(server, 'close');
    server.close();
    await closed;
  }
}

(async function() {
  await testVersion('TLSv1.2');
  await testVersion('TLSv1.3');
  console.log('SESSION_RESULT ' + JSON.stringify({ passed: true, cases }));
})().then(common.mustCall());
