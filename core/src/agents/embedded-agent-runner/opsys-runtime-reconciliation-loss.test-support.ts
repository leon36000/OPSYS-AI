import { createServer as createHttpServer, request as httpRequest } from "node:http";

// Real loopback proxy: lose only one completed native reconciliation response.
function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

export async function startReconciliationProxy(upstreamPort: number, loseResponse: boolean) {
  const errors: unknown[] = [];
  let droppedResponses = 0;
  let requests = 0;
  const pending = new Set<import("node:http").ClientRequest>();
  const sockets = new Set<import("node:net").Socket>();
  const server = createHttpServer((incoming, outgoing) => {
    const chunks: Buffer[] = [];
    let bytes = 0;
    incoming.on("data", (part: Buffer) => {
      bytes += part.length;
      if (bytes > 65536) {
        errors.push({ cause: "request overflow" });
        incoming.destroy();
      } else {
        chunks.push(part);
      }
    });
    incoming.on("error", (error) => {
      errors.push(error);
      outgoing.destroy();
    });
    incoming.on("end", () => {
      requests += 1;
      if (
        requests > 80 ||
        incoming.url !== "/mcp/runtime/it-runtime-ok" ||
        !["POST", "GET", "DELETE"].includes(incoming.method ?? "")
      ) {
        errors.push({ cause: "transport boundary refusal", method: incoming.method });
        outgoing.destroy();
        return;
      }
      const body = Buffer.concat(chunks);
      let tool: string | null = null;
      if (body.length) {
        try {
          const value: unknown = JSON.parse(body.toString());
          if (
            isRecord(value) &&
            value.method === "tools/call" &&
            isRecord(value.params) &&
            typeof value.params.name === "string"
          ) {
            tool = value.params.name;
          }
        } catch {
          errors.push({ cause: "invalid JSON request" });
          outgoing.destroy();
          return;
        }
      }
      const upstream = httpRequest(
        {
          hostname: "127.0.0.1",
          port: upstreamPort,
          method: incoming.method,
          path: incoming.url,
          headers: { ...incoming.headers, host: `127.0.0.1:${upstreamPort}` },
          timeout: 12000,
        },
        (response) => {
          const responseParts: Buffer[] = [];
          let responseBytes = 0;
          response.on("data", (part: Buffer) => {
            responseBytes += part.length;
            if (responseBytes > 1048576) {
              errors.push({ cause: "response overflow" });
              response.destroy();
              outgoing.destroy();
            } else {
              responseParts.push(part);
            }
          });
          response.on("error", (error) => {
            errors.push(error);
            outgoing.destroy();
          });
          response.on("end", () => {
            try {
              const nativeBody = Buffer.concat(responseParts);
              const drop =
                loseResponse &&
                tool === "opsys_runtime_concilier" &&
                droppedResponses === 0 &&
                response.statusCode === 200;
              if (drop) {
                droppedResponses += 1;
              }
              if (drop) {
                outgoing.destroy();
              } else {
                outgoing.writeHead(response.statusCode ?? 502, response.headers);
                outgoing.end(nativeBody);
              }
            } catch (error) {
              errors.push(error);
              outgoing.destroy();
            }
          });
        },
      );
      pending.add(upstream);
      upstream.once("close", () => pending.delete(upstream));
      upstream.on("timeout", () => upstream.destroy(new Error("QA upstream timeout12s")));
      upstream.on("error", (error) => {
        errors.push(error);
        outgoing.destroy();
      });
      upstream.end(body);
    });
  });
  server.on("connection", (socket) => {
    sockets.add(socket);
    socket.once("close", () => sockets.delete(socket));
  });
  await new Promise<void>((done, fail) => {
    server.once("error", fail);
    server.listen(0, "127.0.0.1", done);
  });
  const address = server.address();
  if (!address || typeof address === "string") {
    throw new Error("No proxy loopback port");
  }
  return {
    port: address.port,
    errors,
    droppedResponses: () => droppedResponses,
    close: async () => {
      for (const request of pending) {
        request.destroy();
      }
      for (const socket of sockets) {
        socket.destroy();
      }
      await new Promise<void>((done, fail) => {
        server.close((error) => {
          if (error) {
            fail(error);
          } else {
            done();
          }
        });
      });
    },
  };
}
