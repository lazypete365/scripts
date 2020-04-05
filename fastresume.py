#!/usr/bin/python3
#requires: py3-bencode >= 0.0.3
import os, sys, hashlib, math, time, argparse, itertools
from bencode import bencode, bdecode


def sanitize_bytes(value):
    """
    Some versions of the script have a tendency to bork paths where, if a directory
    name is a number, it gets interpreted as an int. So just in case every directory in
    the path gets tested for type and beaten back into shape if needed.
    """
    if isinstance(value, bytes):
        return value
    elif isinstance(value, int):
        return str(value).encode("utf-8")
    else:
        return value.encode("utf-8")

def custom_decoder(field_type, value):
    if field_type == "key":
        return str(value, "ascii")
    elif field_type == "value":
        return value
    else:
        raise Exception("'field_type' can pass only 'key' and 'value' values")
        
def pieces_generator(files, piece_length):
    """
    shamelessly copy-pasted from 
    https://github.com/jbernhard/scripts/blob/master/verify-torrent
    """
    """
    Generate pieces of files.
    This is a little tricky for multi-file torrents because pieces may overlap
    file boundaries.  The first piece of a file may complete the final partial
    piece from the previous file, and some small files (e.g. nfo) use less than
    one piece.
    Arguments:
        files -- list of files to break into pieces
        piece_length -- size of pieces in bytes
    Yields:
        bytes objects with specified size
    """

    piece = None

    for file in files:
        print('  ' + file)

        with open(file, 'rb') as f:
            # if there is an existing piece [from a previous file]
            # read only enough to complete the piece
            if piece:
                piece += f.read(piece_length - len(piece))

                # only yield if the piece is complete
                if len(piece) == piece_length:
                    yield piece
                else:
                    continue

            # now read full pieces normally
            while True:
                piece = f.read(piece_length)

                # only yield if the piece is complete
                if len(piece) == piece_length:
                    yield piece
                else:
                    break

    # yield the final piece
    if piece:
        yield piece


parser = argparse.ArgumentParser(description='Append fastresume information to torrent.')
parser.add_argument('-i', '--infile', help='Original torrent file.', nargs=1, required=True)
parser.add_argument('-p', '--path', help='Path to the files contained in the torrent.', nargs=1, required=True)
parser.add_argument('-o', '--outfile', help='Output torrent file with fastresume data.', nargs=1, required=True)
parser.add_argument('-v', '--verify', help='Verify all hashes.', action="store_true", default=False, required=False)
parser.add_argument('-c', '--clobber', help='Overwrite target file if it already exists.', action="store_true", default=False, required=False)
parser.add_argument('-r', '--remove', help='Remove fastresume data.', action="store_true", default=False, required=False)
parser.add_argument('--verbose', help='Decodes and dumps the torrent information on screen.', action="store_true", default=False, required=False)
args=parser.parse_args()
torrent_filename=args.infile[0]
content_path=args.path[0]
outfile=args.outfile[0]
verify_hashes=args.verify
remove=args.remove
clobber=args.clobber

if not os.path.isfile(torrent_filename):
    print('Source file does not exist!')
    exit(1)
if os.path.isfile(outfile) and not clobber:
    print('Output file already exists. Use argument --clobber (-c) to overwrite.')
    exit(1)

with open(torrent_filename, 'rb') as torrentfile:
    metadata=bdecode(torrentfile.read(), decoder=custom_decoder)

if remove:
    print('Removing fastresume metadata from torrent...')
    if 'rtorrent' in metadata:
        print('Previous rtorrent configuration found. Deleting...')
        del metadata['rtorrent']
    if 'libtorrent_resume' in metadata:
        print('Previous fastresume data found. Deleting...')
        del metadata['libtorrent_resume']
    if args.verbose:
        print('Dumping torrent metadata...')
        print(metadata)
    with open(outfile,'wb') as output:
        output.write(bencode(metadata))
    exit(0)

if args.verbose:
    print('Dumping torrent metadata...')
    print(metadata)

if 'rtorrent' in metadata:
    print('Previous rtorrent configuration found. Deleting...')
    del metadata['rtorrent']
if 'libtorrent_resume' in metadata:
    print('Previous fastresume data found. Deleting...')
    del metadata['libtorrent_resume']

metadata_fastresume=metadata

files=[]
tsize=0
sanitized_files=[]
if 'info' in metadata:
    if 'piece length' in metadata['info']:
        psize=metadata['info']['piece length']
    if 'files' in metadata['info']:
        print('multi-file torrent')
        for file in metadata['info']['files']:
            file_info={}
            file_info.clear()     
            sanitized_path=[]
            filepath=os.path.join(content_path.encode("utf-8"), sanitize_bytes(metadata['info']['name']))
            for i in file['path']:
                sanitized_path.append(sanitize_bytes(i))
                filepath=os.path.join(filepath,sanitize_bytes(i))
            print(filepath)
            files.append(str(filepath,"utf-8"))
            tsize += file['length']
            #Some torrent files store file attributes here, which is not 100% standard.
            #I would love to clean that extra info if present,
            #but that would change the torrentid and might give tracker problems.
            if 'attr' in file: file_info['attr']=file['attr']
            if 'md5sum' in file: file_info['md5sum']=file['md5sum']
            file_info['length']=file['length']
            file_info['path']=sanitized_path
            sanitized_files.append(file_info)
        metadata_fastresume['info']['files']=sanitized_files
    else:
        print('single-file torrent')
        files.append(os.path.join(content_path,str(metadata['info']['name'], "utf-8")))
        tsize=int(str(metadata['info']['length']))
chunks=int((tsize + psize - 1)/ psize)
if chunks*20 != len(metadata['info']['pieces']):
    print("Inconsistent piece information")


pmod=0
metadata_fastresume['libtorrent_resume']={}
metadata_fastresume['libtorrent_resume']['bitfield']=chunks
metadata_fastresume['libtorrent_resume']['files']=[]
for i, file in enumerate(files):
    if os.path.isfile(file):
        mtime=int(os.stat(file).st_mtime)

        if 'files' in metadata['info']:
            fsize=metadata['info']['files'][i]['length']
        else:
            fsize=1
        if not not pmod :
            fchunks=1
        else:
            fchunks=0
        if pmod >= fsize :
            pmod=pmod - fsize
            fsize=0
        else:
            fsize=fsize - pmod
            pmod=0
        fchunks+= math.ceil(fsize/psize)
        if pmod==0:
            pmod=psize-(fsize%psize)
    else:
        print('Missing files or incorrect download path. Exiting...')
        exit()

    metadata_fastresume['libtorrent_resume']['files'].append({'priority':0 , 'mtime': mtime, 'completed':fchunks})
metadata_fastresume['libtorrent_resume']['uncertain_pieces.timestamp']=int(time.time())

if 'files' in metadata['info']:
    content_path=os.path.join(content_path,str(metadata['info']['name'], "utf-8"))

metadata_fastresume['rtorrent']={
"state": 1,
"state_changed":int(time.time()),
"state_counter":1,
"chunks_wanted":0,
"chunks_done":chunks,
"complete":1,
"hashing":0,
"directory": content_path if os.path.isabs(content_path) else os.path.abspath(content_path),
"tied_to_file":outfile if os.path.isabs(outfile) else os.path.abspath(outfile),
"timestamp_finished":0,
"timestamp_started":int(time.time())
}

print('infohash='+hashlib.sha1(bencode(metadata['info'])).hexdigest())

if verify_hashes:
    print('Verifying hashes...')
    pieces_to_hash=pieces_generator(files, metadata['info']['piece length'])
    hashed_pieces = (hashlib.sha1(piece).digest() for piece in pieces_to_hash)
    allhashes=metadata['info']['pieces']
    hashes=(allhashes[i:i+20] for i in range(0, len(allhashes), 20))
    pairs = itertools.zip_longest(list(hashed_pieces), list(hashes))
    success = all(h1 == h2 for h1, h2 in pairs)
    print('Passed!' if success else 'FAILED', end='\n\n')
    if not success:
        print('Exiting without generating fastresume file...')
        exit(1)

with open(outfile,'wb') as output:
    output.write(bencode(metadata_fastresume))
