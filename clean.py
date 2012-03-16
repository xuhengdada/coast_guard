#!/usr/bin/env python

"""
Given a PSRCHIVE archive clean it up using 'paz'.

Patrick Lazarus, Nov. 11, 2011
"""
import optparse
import sys
import types
import re
import shutil

import numpy as np
import matplotlib.pyplot as plt

import psrchive

import config
import utils
import clean_utils
import errors

cleaners = ['power_wash', 'deep_clean', 'clean_simple', 'clean_iterative']


def power_wash(ar):
    """Power wash RFI out of the data.

        Input:
            ar: The archive to be cleaned.
        Outputs:
            None - The archive is cleaned in place.
    """
    ar.pscrunch()
    ar.remove_baseline()
    ar.dedisperse()

    # Remove profile
    data = ar.get_data().squeeze()
    template = np.apply_over_axes(np.sum, data, (0,1)).squeeze()
    data = clean_utils.remove_profile(data, ar.get_nsubint(), ar.get_nchan(), \
                                        template, 4)

    bad_chans = []
    bad_subints = []
    bad_pairs = []
    std_sub_vs_chan = np.std(data, axis=2)
    print std_sub_vs_chan.shape
    #mean_sub_vs_chan = np.mean(data, axis=2)

    # Identify bad sub-int/channel pairs
    subintweights = clean_utils.get_subint_weights(ar).astype(bool)
    chanweights = clean_utils.get_chan_weights(ar).astype(bool)
    for isub in range(ar.get_nsubint()):
        for ichan in range(ar.get_nchan()):
            plt.figure()
            plt.subplot(2,1,1)
            plt.plot(std_sub_vs_chan[isub, :], 'k-')
            subint = clean_utils.scale_chans(std_sub_vs_chan[isub, :], \
                                                chanweights=chanweights)
            print clean_utils.get_hot_bins(subint)
            plt.subplot(2,1,2)
            plt.plot(subint, 'r-')
            plt.title("Subint #%d" % isub)
            plt.figure()
            plt.subplot(2,1,1)
            plt.plot(std_sub_vs_chan[:, ichan], 'k-')
            chan = clean_utils.scale_subints(std_sub_vs_chan[:, ichan], \
                                                subintweights=subintweights)
            print clean_utils.get_hot_bins(chan)
            plt.subplot(2,1,2)
            plt.plot(chan, 'r-')
            plt.title("Chan #%d" % ichan)
            plt.show() 
    
    chanstds = np.sum(std_sub_vs_chan, axis=0)
    plt.subplot(2,1,1)
    plt.plot(chanstds)
    chanstds = clean_utils.scale_chans(chanstds, chanweights=chanweights)
    plt.subplot(2,1,2)
    plt.plot(chanstds)
    bad_chans.extend(np.argwhere(chanstds > 1).squeeze())
    plt.show()


def deep_clean(ar, unloadfn, chanthresh=5.0, \
                    subintthresh=5.0, binthresh=2.0):
    import psrchive # Temporarily, because python bindings 
                    # are not available on all computers
    #plot(ar, "before_deep_clean")
    
    # First clean channels
    chandata = clean_utils.get_chans(ar, remove_prof=True)
    chanweights = clean_utils.get_chan_weights(ar).astype(bool)
    chanmeans = clean_utils.scale_chans(chandata.mean(axis=1), chanweights=chanweights)
    chanmeans /= clean_utils.get_robust_std(chanmeans, chanweights)
    chanstds = clean_utils.scale_chans(chandata.std(axis=1), chanweights=chanweights)
    chanstds /= clean_utils.get_robust_std(chanstds, chanweights)

    #plt.figure()
    #plt.subplot(2,1,1)
    #plt.plot(chanstds, 'k')
    #plt.axhline(chanthresh, c='k', ls='--')
    #plt.ylabel("Scaled std")
    #plt.subplot(2,1,2)
    #plt.plot(chandata.std(axis=1))

    #plt.figure()
    #plt.subplot(2,1,1)
    #plt.plot(chanmeans, 'k')
    #plt.axhline(chanthresh, c='k', ls='--')
    #plt.ylabel("Scaled mean")
    #plt.subplot(2,1,2)
    #plt.plot(chandata.mean(axis=1))
    #plt.show()
    badchans = np.concatenate((np.argwhere(chanmeans >= chanthresh), \
                                    np.argwhere(chanstds >= chanthresh)))
    badchans = np.unique(badchans)
    utils.print_info("Number of channels to be de-weighted: %d" % len(badchans), 2)
    for ichan in badchans:
        utils.print_info("De-weighting chan# %d" % ichan, 3)
        clean_utils.zero_weight_chan(ar, ichan)

    #plot(ar, "mid-chans_deep_clean")

    # Next clean subints
    subintdata = clean_utils.get_subints(ar, remove_prof=True)
    subintweights = clean_utils.get_subint_weights(ar).astype(bool)
    subintmeans = clean_utils.scale_subints(subintdata.mean(axis=1), \
                                    subintweights=subintweights)
    subintmeans /= clean_utils.get_robust_std(subintmeans, subintweights)
    subintstds = clean_utils.scale_subints(subintdata.std(axis=1), \
                                    subintweights=subintweights)
    subintstds /= clean_utils.get_robust_std(subintstds, subintweights)

    badsubints = np.concatenate((np.argwhere(subintmeans >= subintthresh), \
                                    np.argwhere(subintstds >= subintthresh)))
    
    badsubints = np.unique(badsubints)
    utils.print_info("Number of sub-ints to be de-weighted: %d" % len(badsubints), 2)
    for isub in badsubints:
        utils.print_info("De-weighting subint# %d" % isub, 3)
        clean_utils.zero_weight_subint(ar, isub)

    #plot(ar, "mid-subints_deep_clean")
    
    # Now replace hot bins
    utils.print_info("Will find and clean 'hot' bins", 2)
    clean_utils.clean_hot_bins(ar, thresh=binthresh)
    #plot(ar, "after_deep_clean")
    utils.print_info("Unloading deep cleaned archive as %s" % unloadfn, 2)
    ar.unload(unloadfn)


def clean_simple(ar, timethresh=1.0, freqthresh=3.0):
    plot(ar, "before_simple_clean")
    # Get stats for subints
    subint_stats = get_subint_stats(ar)
    
    # Get stats for chans
    chan_stats = get_chan_stats(ar)

    for isub in np.argwhere(subint_stats >= timethresh):
        print "De-weighting subint# %d" % isub
        zero_weight_subint(ar, isub)
    for ichan in np.argwhere(chan_stats >= freqthresh):
        print "De-weighting chan# %d" % ichan
        zero_weight_chan(ar, ichan)
    plot(ar, "after_simple_clean")
    unloadfn = "%s.cleaned" % ar.get_filename()
    print "Unloading cleaned archive as %s" % unloadfn
    ar.unload(unloadfn)


def clean_iterative(ar, threshold=2.0):
    ii = 0
    while True:
        # Get stats for subints
        subint_stats = get_subint_stats(ar)
        worst_subint = np.argmax(subint_stats)
        
        # Get stats for chans
        chan_stats = get_chan_stats(ar)
        worst_chan = np.argmax(chan_stats)

        # Check that at least something should be masked
        if (chan_stats[worst_chan] < threshold) and \
                    (subint_stats[worst_subint] < threshold):
            break
        else:
            if subint_stats[worst_subint] > chan_stats[worst_chan]:
                print "De-weighting subint# %d" % worst_subint
                zero_weight_subint(ar, worst_subint)
            else:
                print "De-weighting chan# %d" % worst_chan
                zero_weight_chan(ar, worst_chan)
        plot(ar, "bogus_%d" % ii)
        ii += 1
    unloadfn = "%s.cleaned" % ar.get_filename()
    print "Unloading cleaned archive as %s" % unloadfn
    ar.unload(unloadfn)


def prune_band(infn, response=None):
    """Prune the edges of the band. This is useful for
        removing channels where there is no response.
        The file is modified in-place. However, zero-weighting 
        is used for pruning, so the process is reversible.

        Inputs:
            infn: name of file to trim.
            response: A tuple specifying the range of frequencies 
                outside of which should be de-weighted.

        Outputs:
            None
    """
    if response is None:
        response = config.cfg.rcvr_response_lims

    if response is None:
        utils.print_info("No freq range specified for band pruning. Skipping...", 2)
    else:
        lofreq = infn.freq - 0.5*infn.bw
        hifreq = infn.freq + 0.5*infn.bw
        utils.print_info("Pruning frequency band to (%g-%g MHz)" % response, 2)
        utils.execute('paz -m -F "%f %f" -F "%f %f" %s' % \
                        (lofreq, response[0], response[1], hifreq, infn.fn))


def trim_edge_channels(infn, nchan_to_trim=None):
    """Trim the edge channels of an input file to remove 
        band-pass roll-off and the effect of aliasing. 
        The file is modified in-place. However, zero-weighting 
        is used for trimming, so the process is reversible.

        Inputs:
            infn: name of file to trim.
            nchan_to_trim: The number of channels to de-weight at
                each edge of the band.

        Outputs:
            None
    """
    if nchan_to_trim is None:
        nchan_to_trim=config.cfg.nchan_to_trim

    if nchan_to_trim > 0:
        utils.print_info("Trimming %d channels from subband edges " % \
                        nchan_to_trim, 2)
        numchans = int(infn.nchan)
        utils.execute('paz -m -Z "0 %d" -Z "%d %d" %s' % \
                    (nchan_to_trim-1, numchans-nchan_to_trim, numchans-1, infn.fn))


def remove_bad_subints(infn, badsubints=None, badsubint_intervals=None):
    """Zero-weights bad subints.
        The file is modified in-place. However, zero-weighting 
        is used for trimming, so the process is reversible.

        Note: Subints are indexed starting at 0.

        Inputs:
            infn: name of time to remove subints from.
            badchans: A list of subints to remove 
            badchan_intervals: A list of subint intervals 
                (inclusive) to remove
    
        Outputs:
            None
    """
    if badsubints is None:
        badsubints = config.cfg.badsubints
    if badsubint_intervals is None:
        badsubint_intervals = config.cfg.badsubint_intervals

    zaplets = []
    if badsubints:
        zaplets.append("-w '%s'" % " ".join(['%d' % ww for ww in badsubints]))
    if badsubint_intervals:
        zaplets.extend(["-W '%d %d'" % lohi for lohi in badsubint_intervals])

    if zaplets:
        utils.print_info("Removing bad subints.", 2)
        utils.execute("paz -m %s %s" % (" ".join(zaplets), infn.fn))


def remove_bad_channels(infn, badchans=None, badchan_intervals=None, 
                            badfreqs=None, badfreq_intervals=None):
    """Zero-weight bad channels and channels containing bad
        frequencies.
        The file is modified in-place. However, zero-weighting 
        is used for trimming, so the process is reversible.

        Note: Channels are indexed starting at 0.

        Inputs:
            infn: name of time to remove channels from.
            badchans: A list of channels to remove 
            badchan_intervals: A list of channel intervals 
                (inclusive) to remove
            badfreqs: A list of frequencies. The channels
                containing these frequencies will be removed.
            badfreq_intervals: A list of frequency ranges 
                to remove. The channels containing these
                frequencies will be removed.
    
        Outputs:
            None
    """
    if badchans is None:
        badchans = config.cfg.badchans
    if badchan_intervals is None:
        badchan_intervals = config.cfg.badchan_intervals
    if badfreqs is None:
        badfreqs = config.cfg.badfreqs
    if badfreq_intervals is None:
        badfreq_intervals = config.cfg.badfreq_intervals

    zaplets = []
    if badchans:
        zaplets.append("-z '%s'" % " ".join(['%d' % zz for zz in badchans]))
    if badchan_intervals:
        zaplets.extend(["-Z '%d %d'" % lohi for lohi in badchan_intervals])
    if badfreqs:
        zaplets.append("-f '%s'" % " ".join(['%f' % ff for ff in badfreqs]))
    if badfreq_intervals:
        zaplets.extend(["-F '%f %f'" % lohi for lohi in badfreq_intervals])

    if zaplets:
        utils.print_info("Removing bad channels.", 2)
        utils.execute("paz -m %s %s" % (" ".join(zaplets), infn.fn))


def clean_archive(infn, outfn, clean_re=None, *args, **kwargs):
    if clean_re is None:
        clean_re = config.cfg.clean_strategy
    if clean_re is None:
        return

    matching_cleaners = [clnr for clnr in cleaners if re.search(clean_re, clnr)]
    if len(matching_cleaners) == 1:
        ar = psrchive.Archive_load(infn.fn)
        cleaner = eval(matching_cleaners[0])
        utils.print_info("Cleaning using '%s(...)'." % matching_cleaners[0], 2)
        cleaner(ar, outfn, *args, **kwargs)
    else:
        raise errors.CleanError("Bad cleaner selection. " \
                                "'%s' has %d matches." % \
                                (clean_re, len(matching_cleaners)))


def main():
    print ""
    print "         clean.py"
    print "     Patrick  Lazarus"
    print ""
    file_list = args + options.from_glob
    to_exclude = options.excluded_files + options.excluded_by_glob
    to_clean = utils.exclude_files(file_list, to_exclude)
    print "Number of input files: %d" % len(to_clean)
    
    to_clean = [utils.ArchiveFile(fn) for fn in to_clean]
    
    # Read configurations
    for arf in to_clean:
        config.cfg.load_configs_for_archive(arf)
        outfn = utils.get_outfn(options.outfn, arf)
        shutil.copy(arf.fn, outfn)
    
        arf = utils.ArchiveFile(outfn)

        trim_edge_channels(arf)
        prune_band(arf)
        remove_bad_channels(arf)
        remove_bad_subints(arf)
        clean_archive(arf, outfn)
        print "Cleaned archive: %s" % outfn


if __name__=="__main__":
    parser = utils.DefaultOptions(usage="%prog [OPTIONS] FILES ...", \
                        description="Given a list of PSRCHIVE file names " \
                                    "clean RFI from each one. \nNOTE: " \
                                    "The files are cleaned non-desctructively " \
                                    "by applying zero-weighting.")
    parser.add_option('-o', '--outname', dest='outfn', type='string', \
                        help="The output (reduced) file's name. " \
                            "(Default: '%(name)s_%(yyyymmdd)s_%(secs)05d_cleaned.ar')", \
                        default="%(name)s_%(yyyymmdd)s_%(secs)05d_cleaned.ar")
    parser.add_option('-g', '--glob', dest='from_glob', action='callback', \
                        callback=utils.get_files_from_glob, default=[], \
                        type='string', \
                        help="Glob expression of input files. Glob expression " \
                            "should be properly quoted to not be expanded by " \
                            "the shell prematurely. (Default: no glob " \
                            "expression is used.)") 
    parser.add_option('-x', '--exclude-file', dest='excluded_files', \
                        type='string', action='append', default=[], \
                        help="Exclude a single file. Multiple -x/--exclude-file " \
                            "options can be provided. (Default: don't exclude " \
                            "any files.)")
    parser.add_option('--exclude-glob', dest='excluded_by_glob', action='callback', \
                        callback=utils.get_files_from_glob, default=[], \
                        type='string', \
                        help="Glob expression of files to exclude as input. Glob " \
                            "expression should be properly quoted to not be " \
                            "expanded by the shell prematurely. (Default: " \
                            "exclude any files.)")
    parser.add_option('--nchan-to-trim', dest='nchan_to_trim', action='callback', \
                        callback=parser.override_config, type='int', \
                        help="The number of channels to trim from the edge of each " \
                            "subband. (Default: %d)" % config.cfg.nchan_to_trim)
    parser.add_option('--rcvr-response-lims', dest='rcvr_response_lims', \
                        action='callback', callback=parser.override_config, \
                        type='int', nargs=2, \
                        help="Two values containg the low and high frequency " \
                            "limits of the receiver's response (in MHz). Channels " \
                            "outside of this region will be de-weighted. " \
                            "(Default: %s)" % config.cfg.rcvr_response_lims)
    parser.add_option('--clean-strategy', dest='clean_strategy', action='callback', \
                        callback=parser.override_config, type='str', \
                        help="A string that matches one of the names of the available " \
                             "cleaning functions. Possibilities are: %s. (Default: %s) " % \
                             (", ".join(cleaners), config.cfg.clean_strategy))
    options, args = parser.parse_args()
    main()
