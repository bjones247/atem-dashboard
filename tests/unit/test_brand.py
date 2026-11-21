"""The brand (docs/brand/handoff) is wired in: assets exist in every size,
the pages carry the lockup and the legal line, the tray picks per platform."""
import os
import sys
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
BRAND = ROOT / 'atem_control' / 'static' / 'brand'


def test_icon_containers_carry_every_size():
    assert sorted(Image.open(ROOT / 'build/desktop/icon.ico').info['sizes']) == [(s, s) for s in (16, 24, 32, 48, 64, 128, 256)]
    assert sorted(Image.open(BRAND / 'favicon.ico').info['sizes']) == [(16, 16), (32, 32), (48, 48)]
    assert (ROOT / 'build/desktop/icon.icns').stat().st_size > 50_000
    assert Image.open(ROOT / 'build/desktop/icon.png').size == (1024, 1024)
    assert Image.open(BRAND / 'apple-touch-icon.png').getpixel((0, 0))[3] == 255     # square, iOS rounds it
    for name, size in (('tray/mac-22.png', 22), ('tray/mac-44.png', 44), ('tray/win-16.png', 16),
                       ('tray/win-32.png', 32), ('tray/linux-24.png', 24), ('icon-192.png', 192), ('icon-512.png', 512)):
        assert Image.open(BRAND / name).size == (size, size), name


def test_mac_menu_bar_mark_is_the_logo_in_colour():
    """The menu-bar icon is the app's mark, not a tinted silhouette: the
    PGM red and PVW green bars are in it (two-bar form, the 30 px rule)."""
    colours = {px[:3] for px in Image.open(BRAND / 'tray/mac-44.png').convert('RGBA').getdata() if px[3] == 255}
    assert (0xD6, 0x27, 0x18) in colours and (0x2F, 0xD0, 0x7A) in colours


def test_fonts_and_licences_ship():
    for f in ('Archivo-400-latin.woff2', 'Archivo-800-latin.woff2', 'IBMPlexMono-400-latin.woff2', 'IBMPlexMono-600-latin.woff2',
              'OFL-Archivo.txt', 'OFL-IBMPlexMono.txt'):
        assert (BRAND / 'fonts' / f).exists(), f
    css = (BRAND / 'brand.css').read_text()
    assert '--pgm:            #D62718' in css and '--pvw:            #2FD07A' in css
    assert 'font-family: "Archivo"' in css and 'font-family: "IBM Plex Mono"' in css


@pytest.mark.django_db
def test_pages_carry_the_brand(client):
    description = 'an ATEM M/E and virtual switcher based on '
    credit = 'webATEM</a> by Lucas Romanenko'
    launcher = client.get('/launcher/').content.decode()
    assert '<title>webATEM.vs</title>' in launcher
    assert 'brand-wordmark' in launcher and '<span>web</span>ATEM.vs' in launcher
    assert '<span class="ver">v1.1.0</span>' in launcher
    assert description in launcher and credit in launcher
    assert 'Uninstall webATEM.vs?' in launcher
    assert '<svg' in launcher                                    # the inline mark
    connect = client.get('/atem/').content.decode()
    assert '<title>Connect to ATEM - webATEM.vs</title>' in connect
    assert '<span>web</span>ATEM.vs' in connect
    assert 'brand/brand.css' in connect and 'brand/favicon.ico' in connect
    assert 'Browser control for ATEM switchers.' in connect
    # The independence line is the README's (Lucas, 2026-09-14): an operator
    # driving a switcher is not the audience for it, and it read as clutter
    # on both surfaces.
    assert 'Not affiliated' not in connect
    for url, title in (
        ('/atem/control/', 'ATEM Control Panel'),
        ('/atem/live/?ip=192.0.2.4', 'Virtual Switchers'),
        ('/atem/dashboard/', 'Production Dashboard'),
    ):
        html = client.get(url).content.decode()
        assert f'<title>{title} - webATEM.vs</title>' in html
        assert 'aria-label="webATEM.vs"' in html
        if url != '/atem/dashboard/':
            assert '<h3 class="font-bold mb-1">webATEM.vs <span class="font-mono font-normal text-base-content/60">v1.1.0</span></h3>' in html
            assert description in html and credit in html
            assert 'href="https://github.com/lucas-romanenko/webatem"' in html


def test_tray_image_per_platform(monkeypatch):
    from webatem import launcher
    monkeypatch.setattr(sys, 'platform', 'darwin')
    assert launcher._tray_image().size == (22, 22)
    monkeypatch.setattr(sys, 'platform', 'linux')
    monkeypatch.setattr(os, 'name', 'posix')
    assert launcher._tray_image().size == (24, 24)


def test_the_app_installs_to_a_home_screen_as_itself():
    """Saved to a phone's home screen it must be the app, not a bookmark: the
    manifest names it with the wordmark's spelling and hands over icons,
    including a maskable one for Android's launcher shapes."""
    import json
    manifest = json.loads((BRAND / 'manifest.webmanifest').read_text())
    assert manifest['name'] == 'webATEM.vs' and manifest['short_name'] == 'webATEM.vs'
    assert manifest['start_url'] == '/atem/' and manifest['display'] == 'standalone'
    purposes = {i.get('purpose') for i in manifest['icons']}
    assert 'maskable' in purposes, 'Android crops a non-maskable icon to a circle'
    for icon in manifest['icons']:
        f = BRAND / icon['src']
        assert f.exists(), icon['src']
        assert Image.open(f).size == tuple(int(n) for n in icon['sizes'].split('x'))


@pytest.mark.django_db
def test_the_pages_point_at_the_manifest(client):
    html = client.get('/atem/').content.decode()
    assert 'rel="manifest"' in html and 'brand/manifest.webmanifest' in html
    assert 'apple-touch-icon' in html
    assert 'name="application-name" content="webATEM.vs"' in html
    assert 'name="apple-mobile-web-app-title" content="webATEM.vs"' in html


@pytest.mark.django_db
def test_the_manifest_is_served_as_a_manifest(client):
    """WhiteNoise sends nosniff, so a generic content type means the phone
    never reads the manifest and saves a bookmark instead of the app. It
    keeps its own media-type table, separate from the stdlib one."""
    from django.conf import settings
    assert settings.WHITENOISE_MIMETYPES['.webmanifest'] == 'application/manifest+json'
