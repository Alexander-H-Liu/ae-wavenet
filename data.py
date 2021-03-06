import numpy as np
from functools import total_ordering
from sys import stderr

def _greatest_lower_bound(a, q): 
    '''return largest i such that a[i] <= q.  assume a is sorted.
    if q < a[0], return -1'''
    l, u = 0, len(a) - 1 
    while (l < u): 
        m = u - (u - l) // 2 
        if a[m] <= q: 
            l = m 
        else: 
            u = m - 1 
    return l or -1 + (a[l] <= q) 


class VirtualPermutation(object):
    # closest primes to 2^1, ..., 2^40, generated with:
    # for p in $(seq 1 40); do 
    #     i=$(echo ' 2^'$p'' | bc);
    #     primesieve 1 $i -n -q;
    # done
    primes = [3, 5, 11, 17, 37, 67, 131, 257, 521, 1031, 2053, 4099, 8209,
            16411, 32771, 65537, 131101, 262147, 524309, 1048583, 2097169,
            4194319, 8388617, 16777259, 33554467, 67108879, 134217757,
            268435459, 536870923, 1073741827, 2147483659, 4294967311,
            8589934609, 17179869209, 34359738421, 68719476767, 137438953481,
            274877906951, 549755813911, 1099511627791]


    @classmethod
    def n_items(cls, requested_n_items):
        ind = _greatest_lower_bound(cls.primes, requested_n_items)
        if ind == -1:
            raise InvalidArgument
        return cls.primes[ind]


    def __init__(self, rand_state, requested_n_items):
        self.rand_state = rand_state
        self.n_items = self.n_items(requested_n_items)

    def permutation_gen_fn(self, beg, cnt):
        '''
        # Generate cnt elements of a random permutation of [0, self.n_items) 
        # beg is the logical position *within* the virtual permutation.
        # beg can be None, which means there is no previous checkpoint.
        # cnt is the number of positions to return
        From accepted answer:
        https://math.stackexchange.com/questions/2522177/ \
                generating-random-permutations-without-storing-additional-arrays
        '''
        for n in reversed(self.primes):
            if n <= self.n_items:
                break
        assert beg <= n and cnt >= 0 and beg + cnt <= n
        a = self.rand_state.randint(0, n, 1, dtype='int64')[0]
        # We choose a range not too close to 0 or n, so that we get a
        # moderately fast moving circle.
        b = self.rand_state.randint(n//5, (4*n)//5, 1, dtype='int64')[0]
        for iter_pos in range(beg, beg + cnt):
            yield iter_pos, (a + iter_pos*b) % n


class Checkpoint(object):
    def __init__(self, rand_state, lead_wavgen_pos, perm_gen_pos):
        self.lead_wavgen_rand_state = rand_state
        self.lead_wavgen_pos = lead_wavgen_pos
        self.perm_gen_pos = perm_gen_pos
    def __str__(self):
        from pickle import dumps
        from hashlib import md5
        return 'rand: {}, lead_wavgen_pos: {}, perm_gen_pos: {}'.format(
                md5(dumps(self.lead_wavgen_rand_state)).hexdigest(),
                self.lead_wavgen_pos, 
                self.perm_gen_pos)


class WavSlices(object):
    '''
    Outline:
    1. Load the list of .wav files with their IDs into sample_catalog
    2. Generate items from sample_catalog in random order
    3. Load up to wav_buf_sz (nearest prime number lower bound) timesteps
    4. Yield them in a rotation-random order using (a + i*b) mod N technique.

    WavSlices allows a client to read its (WavSlices) full state, and to
    restore its state.  One can thus save/restore checkpoint at an arbitrary
    point, including the start, thus allowing for completely repeatable
    experiments.
    '''

    def __init__(self, sam_file, n_win, recep_field_sz, batch_sz, sample_rate,
            fraction_use_perm, requested_wav_buf_sz):
        '''
        fraction_use_perm:  fraction [0, 1] in which to 
        '''
        self.sam_file = sam_file
        self.batch_sz = batch_sz
        self.n_win = n_win
        self.recep_field_sz = recep_field_sz
        self.sample_rate = sample_rate
        if fraction_use_perm <= 0 or fraction_use_perm > 1.0:
            raise ValueError

        self.frac_use_perm = fraction_use_perm

        self.rand_state = np.random.mtrand.RandomState()
        self.wav_gen = None
        
        # Used in checkpointing
        self.wavgen_rand_state = None
        self.wavgen_pos = None 
        self.lead_wavgen_rand_state = None 
        self.lead_wavgen_pos = None 
        self.perm_gen_pos = None 

        # estimated number of total slices we can process in a buffer
        # of requested size (= number of time steps)
        est_n_slices = int(requested_wav_buf_sz / self.n_win)

        self.perm = VirtualPermutation(self.rand_state, est_n_slices)
        self.wav_buf = []
        self.wav_ids = []
        self.vstart = []
        self.sample_catalog = []
        with open(self.sam_file) as sam_fh:
            for s in sam_fh.readlines():
                (vid, wav_path) = s.strip().split('\t')
                self.sample_catalog.append([int(vid), wav_path])

        self.current_epoch = 1 

    def slice_size(self):
        return self.n_win + self.recep_field_sz - 1


    def get_checkpoint(self):
        if self.lead_wavgen_rand_state is None:
            print('No generator created yet, so no checkpoint defined.')
            return None
        return Checkpoint(self.lead_wavgen_rand_state,
                self.lead_wavgen_pos, self.perm_gen_pos)


    def restore_checkpoint(self, ckpt):
        '''After calling restore_checkpoint, a call to _slice_gen_fn produces a
        generator object with the same state as when it was saved'''
        self.rand_state.set_state(ckpt.lead_wavgen_rand_state)
        self.wav_gen = self._wav_gen_fn(ckpt.lead_wavgen_pos)
        self.lead_wavgen_pos = ckpt.lead_wavgen_pos
        self.perm_gen_pos = ckpt.perm_gen_pos

    
    def _wav_gen_fn(self, pos):
        '''random order generation of one epoch of whole wav files.'''
        import librosa
        self.wavgen_rand_state = self.rand_state.get_state()
        self.wavgen_pos = pos

        def gen_fn():

            shuffle_index = self.rand_state.permutation(len(self.sample_catalog))
            shuffle_catalog = [self.sample_catalog[i] for i in shuffle_index] 
            for iter_pos, s in enumerate(shuffle_catalog[pos:], pos):
                vid, wav_path = s[0], s[1]
                wav, _ = librosa.load(wav_path, self.sample_rate)
                # print('Parsing ', wav_path, file=stderr)
                self.wavgen_pos = iter_pos
                yield iter_pos, vid, wav

            # Completed a full epoch
            self.current_epoch += 1

        return gen_fn()


    def _load_wav_buffer(self):
        '''Fully load the wav file buffer.  Consumes remaining contents of
        current wav_gen, reissuing generators as needed.
        This function relies on the checkpoint state through self.wav_gen and
        self.rand_state
        '''
        vpos = 0
        self.wav_buf = []
        self.wav_ids = []
        self.vstart = []

        if self.wav_gen is None:
            self.wav_gen = self._wav_gen_fn(0)

        self.lead_wavgen_rand_state = self.wavgen_rand_state
        self.lead_wavgen_pos = self.wavgen_pos

        self.offset = self.rand_state.randint(0, self.n_win, 1, dtype='int32')[0] 
        last_v_start = self.offset + (self.perm.n_items - 1) * self.n_win
        while vpos < last_v_start:
            try:
                iter_pos, vid, wav = next(self.wav_gen)
            except StopIteration:
                self.wav_gen = self._wav_gen_fn(0)
                iter_pos, vid, wav = next(self.wav_gen)

            self.wav_buf.append(wav)
            self.wav_ids.append(vid)
            self.vstart.append(vpos)
            vpos += len(wav) - self.slice_size()


    def _slice_gen_fn(self):
        '''
        '''
        self._load_wav_buffer()
        if self.perm_gen_pos is None:
            self.perm_gen_pos = 0

        def gen_fn():
            perm_gen = self.perm.permutation_gen_fn(self.perm_gen_pos,
                    int(self.perm.n_items * self.frac_use_perm))
            for iter_pos, vind in perm_gen:
                vpos = self.offset + vind * self.n_win
                wav_file_ind = _greatest_lower_bound(self.vstart, vpos)
                wav_off = vpos - self.vstart[wav_file_ind]

                # self.perm_gen_pos gives the position that will be yielded next
                self.perm_gen_pos = iter_pos + 1
                yield wav_file_ind, wav_off, vind, \
                        self.wav_ids[wav_file_ind], \
                        self.wav_buf[wav_file_ind][wav_off:wav_off + self.slice_size()]

            # We've exhausted the iterator, next position should be zero
            self.perm_gen_pos = 0
        return gen_fn()


    def batch_slice_gen_fn(self):
        '''infinite generator for batched slices of wav files'''

        def gen_fn(sg):
            b = 0
            wavs = np.empty((self.batch_sz, self.slice_size()), dtype='float64')
            ids = np.empty(self.batch_sz, dtype='int32')
            while True:
                while b < self.batch_sz:
                    try:
                        wav_file_ind, wav_off, vind, wav_id, wav_slice = next(sg)
                    except StopIteration:
                        sg = self._slice_gen_fn()
                        continue
                    wavs[b,:] = wav_slice
                    ids[b] = wav_id
                    b += 1
                yield ids, wavs
                b = 0

        return gen_fn(self._slice_gen_fn())






            


