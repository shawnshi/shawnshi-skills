import { createReadStream, existsSync, realpathSync } from 'node:fs';
import { realpath, stat } from 'node:fs/promises';
import { createServer } from 'node:http';
import { extname, relative, resolve, sep } from 'node:path';

const MIME = new Map([
  ['.html', 'text/html; charset=utf-8'],
  ['.htm', 'text/html; charset=utf-8'],
  ['.css', 'text/css; charset=utf-8'],
  ['.js', 'text/javascript; charset=utf-8'],
  ['.mjs', 'text/javascript; charset=utf-8'],
  ['.json', 'application/json; charset=utf-8'],
  ['.svg', 'image/svg+xml'],
  ['.png', 'image/png'],
  ['.jpg', 'image/jpeg'],
  ['.jpeg', 'image/jpeg'],
  ['.gif', 'image/gif'],
  ['.webp', 'image/webp'],
  ['.avif', 'image/avif'],
  ['.woff', 'font/woff'],
  ['.woff2', 'font/woff2'],
  ['.ttf', 'font/ttf'],
  ['.otf', 'font/otf'],
  ['.mp4', 'video/mp4'],
  ['.webm', 'video/webm'],
  ['.pdf', 'application/pdf']
]);

function isWithin(root, target) {
  const path = relative(root, target);
  return path === '' || (!path.startsWith(`..${sep}`) && path !== '..' && !path.startsWith(sep));
}

function writeError(response, status, message) {
  response.writeHead(status, { 'content-type': 'text/plain; charset=utf-8', 'cache-control': 'no-store' });
  response.end(message);
}

export async function createStaticServer(options = {}) {
  const requestedRoot = resolve(options.root || process.cwd());
  const host = options.host || '127.0.0.1';
  const port = Number(options.port || 0);
  if (!existsSync(requestedRoot)) throw new Error(`Static server root does not exist: ${requestedRoot}`);
  const root = await realpath(requestedRoot);

  const server = createServer(async (request, response) => {
    if (!['GET', 'HEAD'].includes(request.method || 'GET')) {
      response.setHeader('allow', 'GET, HEAD');
      writeError(response, 405, 'Method not allowed');
      return;
    }
    let pathname;
    try {
      pathname = decodeURIComponent(new URL(request.url || '/', `http://${host}`).pathname);
    } catch (_) {
      writeError(response, 400, 'Bad request');
      return;
    }
    if (pathname.includes('\0')) {
      writeError(response, 400, 'Bad request');
      return;
    }

    const unresolvedTarget = resolve(root, `.${pathname}`);
    if (!isWithin(root, unresolvedTarget)) {
      writeError(response, 403, 'Forbidden');
      return;
    }
    try {
      let target = await realpath(unresolvedTarget);
      if (!isWithin(root, target)) throw Object.assign(new Error('Symlink target is outside the server root'), { code: 'EACCES' });
      let info = await stat(target);
      if (info.isDirectory()) {
        target = await realpath(resolve(target, 'index.html'));
        if (!isWithin(root, target)) throw Object.assign(new Error('Symlink target is outside the server root'), { code: 'EACCES' });
        info = await stat(target);
      }
      if (!info.isFile()) throw Object.assign(new Error('Not found'), { code: 'ENOENT' });
      response.writeHead(200, {
        'content-type': MIME.get(extname(target).toLowerCase()) || 'application/octet-stream',
        'content-length': info.size,
        'cache-control': 'no-store',
        'x-content-type-options': 'nosniff'
      });
      if (request.method === 'HEAD') response.end();
      else createReadStream(target).on('error', () => response.destroy()).pipe(response);
    } catch (error) {
      writeError(response, error.code === 'EACCES' ? 403 : 404, error.code === 'EACCES' ? 'Forbidden' : 'Not found');
    }
  });

  await new Promise((resolveListen, reject) => {
    server.once('error', reject);
    server.listen(port, host, () => {
      server.off('error', reject);
      resolveListen();
    });
  });
  const address = server.address();
  const baseUrl = `http://${host}:${address.port}`;

  return {
    root,
    host,
    port: address.port,
    baseUrl,
    urlFor(filePath) {
      const absolute = resolve(filePath);
      const canonical = realpathSync(absolute);
      if (!isWithin(root, canonical)) throw new Error(`Symlink target is outside static server root: ${absolute}`);
      const path = relative(root, canonical).split(sep).map(encodeURIComponent).join('/');
      return `${baseUrl}/${path}`;
    },
    async close() {
      if (!server.listening) return;
      await new Promise((resolveClose, reject) => server.close(error => error ? reject(error) : resolveClose()));
    }
  };
}
