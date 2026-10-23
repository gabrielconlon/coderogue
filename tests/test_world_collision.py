import pytest

from coderogue.world.camera import Camera
from coderogue.world.collision import CollisionGrid, boxes_overlap, move_box

ROOM = [
    "#####",
    "#...#",
    "#...#",
    "#####",
]


def test_blocked_flush_against_wall():
    g = CollisionGrid.from_rows(ROOM)
    r = move_box(g, 20, 20, 10, 10, -30, 0)
    assert r.hit_x and r.x == pytest.approx(16)


def test_slides_along_wall_on_diagonal():
    g = CollisionGrid.from_rows(ROOM)
    # pushing up-left into the top wall: y stops, x keeps moving
    r = move_box(g, 30, 17, 10, 10, -5, -5)
    assert r.hit_y and not r.hit_x
    assert r.y == pytest.approx(16)
    assert r.x == pytest.approx(25)


def test_fast_move_does_not_tunnel():
    g = CollisionGrid.from_rows(["#.#.#"] * 1 + ["#...#"])
    r = move_box(g, 20, 17, 8, 8, 100, 0)
    assert r.x + 8 <= 64 + 1e-6


def test_out_of_bounds_is_solid_and_overlap():
    g = CollisionGrid.from_rows(["..", ".."])
    assert g.is_solid(-1, 0) and g.is_solid(2, 0)
    assert boxes_overlap((0, 0, 10, 10), (5, 5, 10, 10))
    assert not boxes_overlap((0, 0, 10, 10), (10, 0, 10, 10))


def test_camera_clamps_and_centres():
    cam = Camera(320, 180, 640, 192)
    cam.follow(0, 0)
    assert (cam.x, cam.y) == (0, 0)
    cam.follow(1000, 1000)
    assert (cam.x, cam.y) == (320, 12)
    cam.follow(300, 96)
    assert cam.x == 140
    small = Camera(320, 180, 160, 100)
    small.follow(10, 10)
    assert (small.x, small.y) == (-80, -40)
