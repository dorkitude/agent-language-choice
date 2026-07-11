declare module "node:http" {
  export interface IncomingMessage {
    method?: string;
    url?: string;
    setEncoding(encoding: string): void;
    on(event: "data", listener: (chunk: string) => void): this;
    on(event: "end", listener: () => void): this;
    on(event: "error", listener: (error: Error) => void): this;
    destroy(): void;
  }

  export interface ServerResponse {
    headersSent: boolean;
    writeHead(statusCode: number, headers?: Record<string, string | number>): this;
    end(data?: string): void;
  }

  export function createServer(
    listener: (request: IncomingMessage, response: ServerResponse) => void,
  ): {
    listen(port: number, hostname: string): void;
  };
}

declare const process: {
  env: Record<string, string | undefined>;
};
