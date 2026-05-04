import { afterEach, describe, it, expect, beforeEach, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import React from "react";

// Mock the api module BEFORE importing the component under test.
vi.mock("@/lib/api", () => ({
  listPlaylists: vi.fn(),
  createPlaylist: vi.fn(),
  addTracks: vi.fn(),
}));

import AddToPlaylistMenu from "@/components/AddToPlaylistMenu";
import * as api from "@/lib/api";

const mocked = api as unknown as {
  listPlaylists: ReturnType<typeof vi.fn>;
  createPlaylist: ReturnType<typeof vi.fn>;
  addTracks: ReturnType<typeof vi.fn>;
};

beforeEach(() => {
  mocked.listPlaylists.mockReset();
  mocked.createPlaylist.mockReset();
  mocked.addTracks.mockReset();
});

afterEach(() => {
  cleanup();
});

describe("AddToPlaylistMenu", () => {
  it("renders the user's playlists once loaded", async () => {
    mocked.listPlaylists.mockResolvedValueOnce([
      {
        id: 1,
        user_id: 1,
        name: "Chill",
        created_at: "x",
        updated_at: "x",
        track_count: 3,
      },
      {
        id: 2,
        user_id: 1,
        name: "Banger",
        created_at: "x",
        updated_at: "x",
        track_count: 0,
      },
    ]);
    render(<AddToPlaylistMenu trackId="t-1" onClose={() => {}} />);

    expect(await screen.findByText("Chill")).toBeTruthy();
    expect(await screen.findByText("Banger")).toBeTruthy();
  });

  it("clicking a playlist calls addTracks(id, [trackId])", async () => {
    mocked.listPlaylists.mockResolvedValueOnce([
      {
        id: 7,
        user_id: 1,
        name: "Chill",
        created_at: "x",
        updated_at: "x",
        track_count: 0,
      },
    ]);
    mocked.addTracks.mockResolvedValueOnce({ playlist_id: 7, track_count: 1 });

    render(<AddToPlaylistMenu trackId="track-xyz" onClose={() => {}} />);

    const item = await screen.findByTestId("add-to-playlist-item-7");
    fireEvent.click(item);

    await waitFor(() => {
      expect(mocked.addTracks).toHaveBeenCalledWith(7, ["track-xyz"]);
    });
  });

  it("'Create new…' creates a playlist and adds the track", async () => {
    mocked.listPlaylists.mockResolvedValueOnce([]);
    mocked.createPlaylist.mockResolvedValueOnce({
      id: 99,
      user_id: 1,
      name: "Fresh",
      created_at: "x",
      updated_at: "x",
      track_count: 0,
    });
    mocked.addTracks.mockResolvedValueOnce({ playlist_id: 99, track_count: 1 });

    render(<AddToPlaylistMenu trackId="track-abc" onClose={() => {}} />);

    fireEvent.click(await screen.findByTestId("add-to-playlist-new-trigger"));
    const input = await screen.findByTestId("add-to-playlist-new-name");
    fireEvent.change(input, { target: { value: "Fresh" } });
    fireEvent.click(screen.getByTestId("add-to-playlist-new-submit"));

    await waitFor(() => {
      expect(mocked.createPlaylist).toHaveBeenCalledWith("Fresh");
      expect(mocked.addTracks).toHaveBeenCalledWith(99, ["track-abc"]);
    });
  });

  it("calls onAdded after a successful pick", async () => {
    mocked.listPlaylists.mockResolvedValueOnce([
      {
        id: 4,
        user_id: 1,
        name: "Hits",
        created_at: "x",
        updated_at: "x",
        track_count: 0,
      },
    ]);
    mocked.addTracks.mockResolvedValueOnce({ playlist_id: 4, track_count: 1 });
    const onAdded = vi.fn();

    render(
      <AddToPlaylistMenu
        trackId="track-1"
        onAdded={onAdded}
        onClose={() => {}}
      />,
    );
    fireEvent.click(await screen.findByTestId("add-to-playlist-item-4"));

    await waitFor(() => {
      expect(onAdded).toHaveBeenCalledTimes(1);
      expect(onAdded).toHaveBeenCalledWith(
        expect.objectContaining({ id: 4, name: "Hits" }),
      );
    });
  });

  it("surfaces an error if listPlaylists fails", async () => {
    mocked.listPlaylists.mockRejectedValueOnce(new Error("boom"));
    render(<AddToPlaylistMenu trackId="t" onClose={() => {}} />);
    expect(await screen.findByText(/boom/)).toBeTruthy();
  });
});
