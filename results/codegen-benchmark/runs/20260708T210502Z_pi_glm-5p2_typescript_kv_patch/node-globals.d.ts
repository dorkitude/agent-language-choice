// Minimal ambient declarations for the Node.js standard-library bits used by
// solution.ts. We cannot rely on @types/node being installed, so we declare
// just what we need to keep `tsc` clean.

declare module 'fs' {
  export function readFileSync(fd: number, encoding: string): string;
}

declare const process: {
  stdout: {
    write(data: string): boolean;
  };
};

interface Buffer {
  compare(other: Buffer): number;
}

declare const Buffer: {
  from(str: string, encoding?: string): Buffer;
};
