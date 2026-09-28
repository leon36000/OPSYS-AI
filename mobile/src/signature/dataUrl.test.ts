import { decoderDataUrl, extensionDepuisMimeType } from "./dataUrl";

describe("decoderDataUrl", () => {
  test("décode une DataURL PNG valide", () => {
    expect(decoderDataUrl("data:image/png;base64,iVBORw0KGgo=")).toEqual({
      mimeType: "image/png",
      base64: "iVBORw0KGgo=",
    });
  });

  test("décode une DataURL JPEG valide", () => {
    expect(decoderDataUrl("data:image/jpeg;base64,/9j/4AAQSkZJRg==")).toEqual({
      mimeType: "image/jpeg",
      base64: "/9j/4AAQSkZJRg==",
    });
  });

  test("chaîne qui n'est pas une DataURL -> null", () => {
    expect(decoderDataUrl("pas une dataurl")).toBeNull();
  });

  test("préfixe data: sans ';base64,' -> null", () => {
    expect(decoderDataUrl("data:image/png,abc")).toBeNull();
  });

  test("partie base64 vide -> null (signature non tracée)", () => {
    expect(decoderDataUrl("data:image/png;base64,")).toBeNull();
    expect(decoderDataUrl("data:image/png;base64,   ")).toBeNull();
  });

  test("espaces de bordure tolérés", () => {
    expect(decoderDataUrl("  data:image/png;base64,abc==  ")).toEqual({ mimeType: "image/png", base64: "abc==" });
  });
});

describe("extensionDepuisMimeType", () => {
  test("image/png -> png", () => {
    expect(extensionDepuisMimeType("image/png")).toBe("png");
  });

  test("image/jpeg -> jpg", () => {
    expect(extensionDepuisMimeType("image/jpeg")).toBe("jpg");
  });

  test("image/svg+xml -> svg", () => {
    expect(extensionDepuisMimeType("image/svg+xml")).toBe("svg");
  });

  test("type inconnu -> bin, jamais un plantage", () => {
    expect(extensionDepuisMimeType("application/octet-stream")).toBe("bin");
  });
});
