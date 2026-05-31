import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { OperationalArea } from "./OperationalArea";

afterEach(() => vi.restoreAllMocks());

function setFields() {
  fireEvent.change(screen.getByLabelText(/latitude/i), { target: { value: "32.8" } });
  fireEvent.change(screen.getByLabelText(/longitude/i), { target: { value: "-117.2" } });
}

describe("OperationalArea", () => {
  it("posts lat/lng/radius and shows the building count on success", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ origin: { lat: 32.8, lng: -117.2 }, radius_m: 400, count: 7 }),
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<OperationalArea apiBase="http://api" />);
    setFields();
    fireEvent.click(screen.getByRole("button", { name: /set area/i }));

    await waitFor(() => expect(screen.getByText(/7 buildings/i)).toBeTruthy());
    const [url, opts] = fetchMock.mock.calls[0];
    expect(url).toBe("http://api/map/area");
    expect(opts.method).toBe("POST");
    expect(JSON.parse(opts.body)).toEqual({ lat: 32.8, lng: -117.2, radius_m: 400 });
  });

  it("shows an offline error when the fetch returns 503", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false,
      status: 503,
      json: async () => ({ detail: "requires internet" }),
    }));
    render(<OperationalArea apiBase="http://api" />);
    setFields();
    fireEvent.click(screen.getByRole("button", { name: /set area/i }));
    await waitFor(() => expect(screen.getByText(/no internet/i)).toBeTruthy());
  });

  it("disables the button while the request is in flight", async () => {
    let release: (v: unknown) => void = () => {};
    const pending = new Promise((r) => {
      release = r;
    });
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(pending));

    render(<OperationalArea apiBase="http://api" />);
    setFields();
    const button = screen.getByRole("button", { name: /set area/i });
    fireEvent.click(button);

    await waitFor(() => expect((button as HTMLButtonElement).disabled).toBe(true));
    release({ ok: true, json: async () => ({ count: 1 }) });
  });

  it("rejects blank/invalid coordinates without fetching", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    render(<OperationalArea apiBase="http://api" />);
    // No lat/lng entered.
    fireEvent.click(screen.getByRole("button", { name: /set area/i }));
    expect(screen.getByText(/valid lat/i)).toBeTruthy();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
