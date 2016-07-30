#!/usr/bin/env python2

# playmusicdecrypter - decrypt MP3 files from Google Play Music offline storage (All Access)
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software Foundation,
# Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301  USA

__version__ = "2.0nop8"

#
# nop1: added folder.jpg/png downloading
# nop2: modfied outfile naming scheme
# nop3: added folder.jpg/png embedding
# nop4: added albumartist tag
# nop5: imported tag-all-files mod by dchrostowski (not toroughly tested yet)
# nop6: added filename charset normalisation + length limits
# nop7: added better runtime handling for adb and fix trouble with non-ascii symbols in file paths mod by nqxcode
# nop8: added keep-encoded-files option to retain encoded files after decryption (=in case of a mess up theres no need to retransfer everything)
#

import os, sys, struct, re, glob, optparse, time
import Crypto.Cipher.AES, Crypto.Util.Counter
import mutagen
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, APIC
from mutagen.mp4 import MP4
from mutagen.mp4 import MP4Cover
import sqlite3
import urllib
import superadb
import unicodedata
reload(sys)
sys.setdefaultencoding('utf8')

class PlayMusicDecrypter:
    """Decrypt MP3 file from Google Play Music offline storage (All Access)"""
    def __init__(self, database, infile, tag_all=False, keep_encoded=False):
        self.nameproblem = False
        # Open source file
        self.infile = infile
        self.source = open(infile, "rb")
        self.is_encrypted = True

        # Test if source file is encrypted
        start_bytes = self.source.read(4)
        if start_bytes != "\x12\xd3\x15\x27":
        	self.is_encrypted = False
        	
        if not self.is_encrypted and not tag_all:
            raise ValueError("Invalid file format!")

        # Get file info
        self.database = database
        self.info = self.get_info()
        self.info["XTitle"] = unicodedata.normalize('NFKD', self.info["Title"]).encode('ascii','ignore').strip()
        self.info["XAlbum"] = unicodedata.normalize('NFKD', self.info["Album"]).encode('ascii','ignore').strip()
        self.info["XArtist"] = unicodedata.normalize('NFKD', self.info["Artist"]).encode('ascii','ignore').strip()
        self.info["XAlbumArtist"] = unicodedata.normalize('NFKD', self.info["AlbumArtist"]).encode('ascii','ignore').strip()
        self.info["XComposer"] = unicodedata.normalize('NFKD', self.info["Composer"]).encode('ascii','ignore').strip()
        self.info["XGenre"] = unicodedata.normalize('NFKD', self.info["Genre"]).encode('ascii','ignore').strip()


    def decrypt(self):
        """Decrypt one block"""
        data = self.source.read(1024)
        if not data:
            return ""

        iv = data[:16]
        encrypted = data[16:]

        counter = Crypto.Util.Counter.new(64, prefix=iv[:8], initial_value=struct.unpack(">Q", iv[8:])[0])
        cipher = Crypto.Cipher.AES.new(self.info["CpData"], Crypto.Cipher.AES.MODE_CTR, counter=counter)

        return cipher.decrypt(encrypted)

    def decrypt_all(self, outfile=""):
        """Decrypt all blocks and write them to outfile (or to stdout if outfile in not specified)"""
        destination = open(outfile, "wb") if outfile else sys.stdout
        while True:
            if self.is_encrypted:
                decrypted = self.decrypt()
            else:
            	source = open(self.infile, 'rb').read()
            	
            if not decrypted:
                break

            destination.write(decrypted)
            destination.flush()

    def get_info(self):
        """Returns informations about song from database"""
        db = sqlite3.connect(self.database, detect_types=sqlite3.PARSE_DECLTYPES)
        db.row_factory = sqlite3.Row
        cursor = db.cursor()

        cursor.execute("""SELECT Title, Album, Artist, AlbumArtist, Composer, Genre, Year, Duration,
                                 TrackCount, TrackNumber, DiscCount, DiscNumber, Compilation, CpData, AlbumId, SongId, AlbumArtLocation, ArtistId
                          FROM music
                          WHERE LocalCopyPath = ?""", (os.path.basename(self.infile),))
        row = cursor.fetchone()
        if row:
            return dict(row)
        else:
            raise ValueError("Empty file info!")

    def normalize_filename(self, filename):
        """Remove invalid characters from filename"""
        a = re.sub(r'[<>:"/\\|?*]', " ", filename)
        return unicode(a)

    def get_outfile(self, truncate=False):
    	if self.info is None:
    		return self.infile
        """Returns output filename based on song informations"""
        tmpdata1 = u"{XAlbumArtist}".format(**self.info)
        
        if len(tmpdata1) > 127:
            #print("Err1:"+tmpdata1)
            tmpdata1= u"[{AlbumId}]".format(**self.info)
            tmpdata2= u"[{AlbumId}] - {XAlbum} ({Year})".format(**self.info)
            self.nameproblem = True
        else:
            tmpdata2= u"{XAlbumArtist} - {XAlbum} ({Year})".format(**self.info)
        if len(tmpdata2) > 127:
            #print("Err2:"+tmpdata2)
            tmpdata2= u"[{AlbumId}] - [{ArtistId}] ({Year})".format(**self.info)
            self.nameproblem = True
        
        destination_dir = os.path.join(self.normalize_filename(tmpdata1), self.normalize_filename(tmpdata2))
        
        filename = u"{DiscNumber:02d}{TrackNumber:02d} - {XArtist} - {XTitle}".format(**self.info)
        filename = (filename[:121] + '...mp3') if len(filename) > 127 else filename + '.mp3'

        if len(filename) > 127:
            #print("Err3:["+filename+"]")
            filename = u"{DiscNumber:02d}{TrackNumber:02d} - {XTitle}.mp3".format(**self.info)
            self.nameproblem = True
        if len(filename) > 127:
            #print("Err4:["+filename+"]")
            filename = u"{DiscNumber:02d}{TrackNumber:02d}.mp3".format(**self.info)
            self.nameproblem = True
        	
        return os.path.join(destination_dir, self.normalize_filename(filename))

    def get_coverpath(self):
        """Returns output filename based on song informations"""
        tmpdata1 = u"{XAlbumArtist}".format(**self.info)
        if len(tmpdata1) > 127:
            #print("Err5:"+tmpdata1)
            tmpdata1= u"[{AlbumId}]".format(**self.info)
            tmpdata2= u"[{AlbumId}] - {XAlbum} ({Year})".format(**self.info)
            self.nameproblem = True
        else:
            tmpdata2= u"{XAlbumArtist} - {XAlbum} ({Year})".format(**self.info)
        if len(tmpdata2) > 127:
            #print("Err6:"+tmpdata2)
            tmpdata2= u"[{AlbumId}] - [{ArtistId}] ({Year})".format(**self.info)
            self.nameproblem = True

        destination_dir = os.path.join(self.normalize_filename(tmpdata1), self.normalize_filename(tmpdata2))
        return os.path.join(destination_dir, "Folder.")

    def update_id3(self, outfile, coverpath):
        """Update ID3 tags in outfile"""
        audio = mutagen.File(outfile, easy=True)
        audio.add_tags()
        
        audio["title"] = self.info["Title"]
        audio["album"] = self.info["Album"]
        audio["artist"] = self.info["Artist"]
        audio["performer"] = self.info["AlbumArtist"]
        audio["albumartist"] = self.info["AlbumArtist"]
        audio["composer"] = self.info["Composer"]
        audio["genre"] = self.info["Genre"]
        audio["date"] = str(self.info["Year"])
        audio["tracknumber"] = str(self.info["TrackNumber"])
        audio["discnumber"] = str(self.info["DiscNumber"])
        audio["compilation"] = str(self.info["Compilation"])
        audio.save()
        
        try:
            if not os.path.isfile(coverpath + 'jpg') and not os.path.isfile(coverpath + 'png'):
                coverfile = urllib.URLopener()
                coverfile.retrieve(str(self.info["AlbumArtLocation"]).strip(), coverpath + 'tmp')
        except:
            self.nameproblem = True
            pass
        
        try:
            if os.path.isfile(coverpath + 'tmp'):
                imagedata=open(coverpath + 'tmp','rb').read()
                if imagedata[1]=='P':
                	os.rename(coverpath + 'tmp', coverpath + 'png')
                else:
                	os.rename(coverpath + 'tmp', coverpath + 'jpg')
        except:
            self.nameproblem = True
            pass    

        try:
            filetype = ''
            fileext = ''
            if os.path.isfile(coverpath + 'png'):
            	filetype = 'image/png'
            	fileext = 'png'
            elif os.path.isfile(coverpath + 'jpg'):
            	filetype = 'image/jpeg'
            	fileext = 'jpg'

            if fileext != '':
                imagedata=open(coverpath + fileext,'rb').read()
                audio = MP3(outfile, ID3=ID3)
                audio.tags.add(APIC(encoding=3, mime=filetype, type=3, u='covr', data=imagedata))
                audio.save()
        except:
            self.nameproblem = True
       	    pass

def is_empty_file(filename):
    """Returns True if file doesn't exist or is empty"""
    return False if os.path.isfile(filename) and os.path.getsize(filename) > 0 else True


def pull_database(destination_dir=".", adb="adb"):
    """Pull Google Play Music database from device"""
    print("Downloading Google Play Music database from device...")
    try:
        adb = superadb.SuperAdb(executable=adb)
    except RuntimeError as e:
        print("  {} Exiting...".format(e.message))
        sys.exit(1)

    if not os.path.isdir(destination_dir):
        os.makedirs(destination_dir)

    db_file = os.path.join(destination_dir, "music.db")
    adb.pull("/data/data/com.google.android.music/databases/music.db", db_file)
    if is_empty_file(db_file):
        print("  Download failed! Exiting...")
        sys.exit(1)


def pull_library(source_dir="/data/data/com.google.android.music/files/music/", destination_dir="encrypted", adb="adb"):
    """Pull Google Play Music library from device"""
    print("Downloading encrypted MP3 files from device...")
    try:
        adb = superadb.SuperAdb(executable=adb)
    except RuntimeError as e:
        print("  {} Exiting...".format(e.message))
        sys.exit(1)

    if not os.path.isdir(destination_dir):
        os.makedirs(destination_dir)

    files = [f for f in adb.ls(source_dir) if f.endswith(".mp3")]
    if files:
        start_time = time.time()
        for i, f in enumerate(files):
            sys.stdout.write("\r  Downloading file {}/{}...".format(i + 1, len(files)))
            sys.stdout.flush()
            adb.pull(os.path.join(source_dir, f), os.path.join(destination_dir, f))
        print("")
        print("  All downloads finished ({:.1f}s)!".format(time.time() - start_time))
    else:
        print("  No files found! Exiting...")
        sys.exit(1)


def decrypt_files(source_dir="encrypted", destination_dir=".", database="music.db", tag_all=False, keep_encoded=False):
    """Decrypt all MP3 files in source directory and write them to destination directory"""
    print("Decrypting MP3 files...")
    if not os.path.isdir(destination_dir):
        os.makedirs(destination_dir)

    files = glob.glob(os.path.join(source_dir, "*.mp3"))
    if files:
        start_time = time.time()
        for f in files:
            try:
                decrypter = PlayMusicDecrypter(database, f, tag_all)
                action = "Decrypting" if decrypter.is_encrypted else "Copying"
                print(u"{} file {} -> {}".format(action, f, decrypter.get_outfile()))
            except ValueError as e:
                print(u"  Skipping file {} ({})".format(f, e))
                continue

            outfile = os.path.join(destination_dir, decrypter.get_outfile())
            if not os.path.isdir(os.path.dirname(outfile)):
                os.makedirs(os.path.dirname(outfile))

            coverpath = os.path.join(destination_dir, decrypter.get_coverpath())
            decrypter.decrypt_all(outfile)
            decrypter.update_id3(outfile, coverpath)
            decrypter.source.close()
            if not decrypter.nameproblem and not keep_encoded:
                os.remove(f)
        print("  Decryption finished ({:.1f}s)!".format(time.time() - start_time))
    else:
        print("  No files found! Exiting...")
        sys.exit(1)


def main():
    # Parse command line options
    parser = optparse.OptionParser(description="Decrypt MP3 files from Google Play Music offline storage (All Access)",
                                   usage="usage: %prog [-h] [options] [destination_dir]",
                                   version="%prog {}".format(__version__))
    parser.add_option("-a", "--adb", default="adb",
                      help="path to adb executable")
    parser.add_option("-d", "--database",
                      help="local path to Google Play Music database file (will be downloaded from device via adb if not specified)")
    parser.add_option("-l", "--library",
                      help="local path to directory with encrypted MP3 files (will be downloaded from device via adb if not specified")
    parser.add_option("-r", "--remote", default="/data/data/com.google.android.music/files/music/",
                      help="remote path to directory with encrypted MP3 files on device (default: %default)")
    parser.add_option("-t", "--tag_all", action="store_true", dest="tag_all_files",                      
                      help="Add ID3 tags to all files and copy to export directory.")
    parser.add_option("-k", "--keep-encoded", action="store_true", dest="keep_encoded",                      
                      help="Keep encoded files (do not delete encoded files after decryption)")
    (options, args) = parser.parse_args()

    if len(args) < 1:
        destination_dir = "."
    else:
        destination_dir = args[0]

    # Download Google Play Music database from device via adb
    if not options.database:
        options.database = os.path.join(destination_dir, "music.db")
        pull_database(destination_dir, adb=options.adb)

    # Download encrypted MP3 files from device via adb
    if not options.library:
        options.library = os.path.join(destination_dir, "encrypted_tmp")
        pull_library(options.remote, options.library, adb=options.adb)

    decrypted_path = os.path.join(destination_dir, "dec")
    
    # Decrypt all MP3 files
    decrypt_files(options.library, decrypted_path, options.database, options.tag_all_files, options.keep_encoded)


if __name__ == "__main__":
    main()
