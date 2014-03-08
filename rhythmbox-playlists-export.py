#! /usr/bin/env python

# Author: Kyle Dickerson
# email: kyle.dickerson@gmail.com
# date: June 14, 2012

import dbus
import os
import glob
import re
import urllib
import time
from xml.etree.ElementTree import Element, ElementTree
import logging
logging.basicConfig(level=logging.DEBUG) # filename='example.log',
# Assumes base paths of local and remote media do not have special characters
#  Rhythmbox uses some form of URI encoding that doesn't match what urllib.quote() gives you
#  So until I can figure out how to reliably replicate their quoting scheme, this won't support special characters in the base paths

# Need to be configured
local_username = 'jessica'
local_media = ["/home/%s/%s" % (local_username, x) for x in ["Music", "Audiobooks", "Podcasts"]]
local_playlists = '/tmp/rhythmbox_sync'
remote_username = 'kyle'
remote_host = "192.168.1.15" # Assumes passwordless SSH authentication available, uses rsync+ssh to move files
remote_media = "/media/sheevaStorage/Music/Jess"
remote_playlists = '/media/sheevaStorage/Playlists'

EXPORT_PLAYLISTS = True
KEEP_LOCAL_PLAYLIST_EXPORT = False
PLAYLIST_FORMAT = 'M3U' # only M3U currently supported, See note about Rhythmbox URI encoding above which also pertains to PLS support
SYNC_RHYTHMBOX = False
SYNC_MEDIA = True
SYNC_PLAYLISTS = True
DRY_RUN = True # Don't actually rsync anything

# Probably correct from above configuration
local_media_bases = [x[:x.rfind('/')] for x in local_media]
local_rhythmbox = "/home/%s/.local/share/rhythmbox" % (local_username)
local_coverart = "/home/%s/.cache/rhythmbox/covers" % (local_username)
remote_rhythmbox = "/home/%s/.local/share/rhythmbox" % (remote_username)
remote_coverart = "/home/%s/.cache/rhythmbox/covers" % (remote_username)
rhythmdb_filename = 'rhythmdb.xml'
playlists_filename = 'playlists.xml'
rhythmbox_startup_wait = 10 # seconds, if Rhythmbox hasn't finished initializing the exports won't work (haven't found a programmatic way to check this)
rhythmbox_shutdown_wait = 3 # seconds
skip_playlists = ['Recently Added', 'Recently Played']

if not os.path.exists(local_playlists):
  logging.info("Creating directory for local export")
  os.makedirs(local_playlists)

def export_playlists():
  logging.info("Exporting playlists...")
  clean_names_regex = re.compile(r'[^\w\s]')
  sessionBus = dbus.SessionBus()
  playlistManager = sessionBus.get_object('org.gnome.Rhythmbox3', '/org/gnome/Rhythmbox3/PlaylistManager')
  asM3U = (PLAYLIST_FORMAT == 'M3U')
  logging.debug("asM3U: %s" % (asM3U))
  for playlistName in playlistManager.GetPlaylists(dbus_interface='org.gnome.Rhythmbox3.PlaylistManager'):
    if playlistName in skip_playlists: continue
    filename = "%s.%s" % (re.sub(clean_names_regex, '_', playlistName), PLAYLIST_FORMAT.lower())
    logging.info("Exporting '%s' to '%s'" % (playlistName, filename))
    try:
      fileURI = 'file://%s/%s' % (local_playlists, filename)
      logging.debug("URI: %s" % (fileURI))
      playlistManager.ExportPlaylist(playlistName, fileURI, asM3U, dbus_interface='org.gnome.Rhythmbox3.PlaylistManager')
    except dbus.exceptions.DBusException as ex:
      logging.error("Failed to export playlist: %s" % (playlistName))
      if ex.get_dbus_name().find('Error.NoReply') > -1:
        logging.error("Perhaps it was empty?  Attempting to restart Rhythmbox...")
        os.system('rhythmbox-client --check-running')
        logging.info('Pausing %d seconds for Rhythmbox initialization' % (rhythmbox_startup_wait))
        time.sleep(rhythmbox_startup_wait) # rhythmbox isn't ready until shortly after rhythmbox-client returns
        playlistManager = sessionBus.get_object('org.gnome.Rhythmbox3', '/org/gnome/Rhythmbox3/PlaylistManager')
      else:
        logging.error("%s:%s" % (ex.get_dbus_name(), ex.get_dbus_message()))
        break

def sync_rhythmbox():
  logging.info("Syncing Rhythmbox data...")
  elementTree = ElementTree()
  elementDB = elementTree.parse("%s/%s" % (local_rhythmbox, rhythmdb_filename))
  # Process all entry -> location entries
  logging.debug("Processing rhythmdb.xml to update file paths")
  for entry in elementDB.iter('entry'):
    loc = entry.find('location')
    if not loc.text.startswith('file://'): continue
    success = False
    for media_loc in local_media_bases:
      if loc.text.find(media_loc) > -1:
        loc.text = loc.text.replace(media_loc, remote_media)
        success = True        
        break
    if not success:
      logging.error("Couldn't figure out how to modify file location for remote use: %s" % (loc.text))
  elementTree.write("%s/%s" % (local_playlists, rhythmdb_filename))

  element = elementTree.parse("%s/%s" % (local_rhythmbox, playlists_filename))
  # Process all playlist -> location entries
  logging.debug("Processing playlists.xml to update file paths")
  for playlist in element.iter('playlist'):
    for loc in playlist.iter('location'):
      success = False
      for media_loc in local_media_bases:
        if loc.text.find(media_loc) > -1:
          loc.text = loc.text.replace(media_loc, remote_media)
          success = True          
          break
      if not success:
        logging.error("Couldn't figure out how to modify file location for remote use: %s" % (loc.text))
  elementTree.write("%s/%s" % (local_playlists, playlists_filename))
  logging.debug("Using rsync to copy xml files")
  if not DRY_RUN:
    cmd = 'rsync -vrlptgz -e ssh "%s/"*.xml "%s@%s:%s" --delete-excluded' % (local_playlists, remote_username, remote_host, remote_rhythmbox)
    logging.debug('Executing: %s' % (cmd))
    os.system(cmd)
    
    cmd = 'rsync -vrlptgz -e ssh "%s/" "%s@%s:%s" --delete-excluded' % (local_coverart, remote_username, remote_host, remote_coverart)
    logging.debug('Executing: %s' % (cmd))
    os.system(cmd)


def sync_media():
  logging.info("Syncing media files...")
  if not DRY_RUN:
    for media_loc in local_media:
      cmd = 'rsync -vrlptgz --chmod=Du=rwx,Dg=rx,Do=rx,Fu=rw,Fg=r,Fo=r -e ssh "%s" "%s@%s:%s/" --delete-excluded' % (media_loc, remote_username, remote_host, remote_media)
      logging.debug('Executing: %s' % (cmd))
      os.system(cmd)


def sync_playlists():
  logging.info("Syncing playlists...")
  alterred_playlists = "%s/%s" % (local_playlists, "alterred")
  if not os.path.exists(alterred_playlists):
    os.makedirs(alterred_playlists)
  for filename in glob.glob("%s/*.%s" % (local_playlists, PLAYLIST_FORMAT.lower())):
    playlist = open(filename, 'r')  
    playlist_text = playlist.readlines()
    playlist.close()
    playlist_text_out = []
    for line in playlist_text:
      if line.startswith('#'):
        playlist_text_out.append(line)
        continue
      success = False
      for media_loc in local_media_bases:
        if line.find(media_loc) > -1:
          playlist_text_out.append(line.replace(media_loc, remote_media))
          success = True
          break
      if not success:
        logging.error("Couldn't determine how to modify file location for remote use: %s" % (line))
    playlist_out = open("%s/%s" % (alterred_playlists, filename[filename.rfind('/')+1:]), 'w')
    playlist_out.writelines(playlist_text_out)
    playlist_out.close()
  if not DRY_RUN:
    cmd = 'rsync -vrlptgz -e ssh "%s/"*.%s "%s@%s:%s" --delete-excluded' % (alterred_playlists, PLAYLIST_FORMAT.lower(), remote_username, remote_host, remote_playlists)
    logging.debug('Executing: %s' % (cmd))
    os.system(cmd)


if EXPORT_PLAYLISTS:
  os.system('rhythmbox-client --check-running')
  logging.info('Pausing %d seconds for Rhythmbox initialization' % (rhythmbox_startup_wait))
  time.sleep(rhythmbox_startup_wait) # rhythmbox isn't ready until shortly after rhythmbox-client returns
  export_playlists()

if SYNC_RHYTHMBOX:
  # can't quit from DBus?
  time.sleep(1)
  os.system('rhythmbox-client --quit')
  logging.info('Pausing %d seconds for Rhythmbox shutdown' % (rhythmbox_shutdown_wait))
  time.sleep(rhythmbox_shutdown_wait)
  sync_rhythmbox()

if SYNC_MEDIA:
  sync_media()

if SYNC_PLAYLISTS:
  sync_playlists()

if not KEEP_LOCAL_PLAYLIST_EXPORT:
  logging.info("Removing folder used for local export")
  os.system('rm -rf %s' % (local_playlists))
