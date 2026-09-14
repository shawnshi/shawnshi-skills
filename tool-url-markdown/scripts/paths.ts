import os from "node:os";
import path from "node:path";
import { mkdir, mkdtemp, rm } from "node:fs/promises";

// Only a CLI-selected directory opts into persistence; environment variables do not.
export async function createChromeProfile(persistentDirectory?: string): Promise<{ directory: string; cleanup: () => Promise<void> }> {
  if (persistentDirectory) {
    const directory = path.resolve(persistentDirectory);
    await mkdir(directory, { recursive: true });
    return { directory, cleanup: async () => {} };
  }
  const directory = await mkdtemp(path.join(os.tmpdir(), "tool-url-markdown-"));
  return { directory, cleanup: () => rm(directory, { recursive: true, force: true, maxRetries: 3, retryDelay: 200 }) };
}
