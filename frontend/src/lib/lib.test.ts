import { describe, expect, it } from "vitest";
import { ApiError } from "../api/client";
import { describeError } from "./errors";
import { checkFiles, MAX_FILE_BYTES } from "./files";
import { formatDateTime } from "./format";
import { sourceLabel } from "./labels";

function file(name: string, size = 100): File {
  return new File([new Uint8Array(size)], name);
}

describe("formatDateTime", () => {
  it("muestra la hora de Córdoba en formato dd/mm/aaaa HH:mm", () => {
    expect(formatDateTime("2026-11-13T15:22:10.842165Z")).toBe("13/11/2026 12:22");
  });
  it("tolera fechas inválidas", () => {
    expect(formatDateTime("no es una fecha")).toBe("");
  });
});

describe("describeError", () => {
  it("traduce códigos conocidos y nunca muestra JSON crudo", () => {
    expect(describeError(new ApiError(503, "llm_unavailable", "x"))).toMatch(/asistente no está disponible/);
    expect(describeError(new ApiError(502, "extraction_failed", "x"))).toMatch(/No pudimos interpretar/);
    expect(describeError(new ApiError(0, "network_error", "x"))).toMatch(/conectar con el servidor/);
  });
  it("no filtra el detalle de errores 5xx", () => {
    const text = describeError(new ApiError(500, "algo_raro", 'Traceback (most recent call last) {"a":1}'));
    expect(text).not.toMatch(/Traceback|\{/);
  });
  it("incluye la espera del 429", () => {
    expect(describeError(new ApiError(429, "rate_limited", "x", 37))).toMatch(/37 segundos/);
  });
  it("mantiene el detalle en español de los 409", () => {
    expect(describeError(new ApiError(409, "invalid_state_transition", "Transición no permitida"))).toBe(
      "Transición no permitida",
    );
  });
});

describe("checkFiles", () => {
  it("rechaza tipos no soportados", () => {
    const { accepted, errors } = checkFiles([], [file("virus.exe")]);
    expect(accepted).toHaveLength(0);
    expect(errors[0]).toMatch(/solo se admiten/);
  });
  it("rechaza archivos de más de 15 MB", () => {
    const big = file("grande.pdf", MAX_FILE_BYTES + 1);
    expect(checkFiles([], [big]).errors[0]).toMatch(/15 MB/);
  });
  it("acepta como máximo 5 archivos", () => {
    const six = Array.from({ length: 6 }, (_, i) => file(`a${i}.png`));
    const { accepted, errors } = checkFiles([], six);
    expect(accepted).toHaveLength(5);
    expect(errors.join(" ")).toMatch(/Máximo 5/);
  });
  it("acepta pdf, png, jpg, jpeg y webp sin distinguir mayúsculas", () => {
    const names = ["a.PDF", "b.png", "c.JPG", "d.jpeg", "e.webp"];
    expect(checkFiles([], names.map((n) => file(n))).accepted).toHaveLength(5);
  });
});

describe("sourceLabel", () => {
  it("muestra las cláusulas como «Cláusula Sexta»", () => {
    expect(sourceLabel("clausula:SEXTA")).toBe("Cláusula Sexta");
    expect(sourceLabel("manual.pdf")).toBe("manual.pdf");
  });
});
