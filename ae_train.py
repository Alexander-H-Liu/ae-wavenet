import torch
import wave_encoder as we
import ae_model as ae


sample_rate = 16000 # timestep / second
sample_rate_ms = int(sample_rate / 1000) # timestep / ms 
window_length_ms = 25 # ms
hop_length_ms = 10 # ms
n_mels = 80
n_mfcc = 13

def get_args():
    import argparse
    import configparser as cp

    conf_parser = argparse.ArgumentParser(add_help=False)
    conf_parser.add_argument("-c", "--conf_file",
            help="Specify config file", metavar="FILE")
    conf_parser.add_argument('--arch-file', '-af', type=str, metavar='ARCH_FILE',
            help='INI file specifying architectural parameters')
    conf_parser.add_argument('--par-file', '-pf', type=str, metavar='PAR_FILE',
            help='INI file specifying training and other hyperparameters')

    args, remaining_argv = conf_parser.parse_known_args()
    if args.arch_file:
        config = cp.SafeConfigParser()
        config.read([args.arch_file])
        arch_defaults = dict(config.items("Defaults"))

    if args.par_file:
        config = cp.SafeConfigParser()
        config.read([args.par_file])
        par_defaults = dict(config.items("Defaults"))

    # Don't surpress add_help here so it will handle -h
    parser = argparse.ArgumentParser(
            # Inherit options from config_parser
            parents=[conf_parser],
            # print script description with -h/--help
            description=__doc__,
            # Don't mess with format of description
            formatter_class=argparse.RawDescriptionHelpFormatter,
            #description='WaveNet Autoencoder Training'
            )
    parser.add_argument('--resume-step', '-rs', type=int, metavar='INT',
            help='Resume training from '
            + 'CKPT_DIR/<ckpt_pfx>-<resume_step>.')
    parser.add_argument('--cpu-only', '-cpu', action='store_true', default=False,
            help='If present, do all computation on CPU')
    parser.add_argument('--save-interval', '-si', type=int, default=1000, metavar='INT',
            help='Save a checkpoint after this many steps each time')
    parser.add_argument('--progress-interval', '-pi', type=int, default=10, metavar='INT',
            help='Print a progress message at this interval')
    parser.add_argument('--max-steps', '-ms', type=int, default=1e20,
            help='Maximum number of training steps')

    # Training parameter overrides
    parser.add_argument('--batch-size', '-bs', type=int, metavar='INT',
            help='Batch size (overrides PAR_FILE setting)')
    parser.add_argument('--slice-size', '-ss', type=int, metavar='INT',
            help='Slice size (overrides PAR_FILE setting)')
    #parser.add_argument('--l2-factor', '-l2', type=float, metavar='FLOAT',
    #        help='Loss = Xent loss + l2_factor * l2_loss')
    parser.add_argument('--learning-rate', '-lr', type=float, metavar='FLOAT',
            help='Learning rate (overrides PAR_FILE setting)')

    # positional arguments
    parser.add_argument('ckpt_path', type=str, metavar='CKPT_PATH_PFX',
            help='E.g. /path/to/ckpt/pfx, a path and '
            'prefix combination for writing checkpoint files')
    parser.add_argument('sam_file', type=str, metavar='SAMPLES_FILE',
            help='File containing lines:\n'
            + '<id1>\t/path/to/sample1.flac\n'
            + '<id2>\t/path/to/sample2.flac\n')
    args = parser.parse_args(remaining_argv)
    return args



def main():
    args = get_args()

    from sys import stderr

    # args consistency checks
    if args.num_global_cond is None and 'n_gc_category' not in arch:
        print('Error: must provide n_gc_category in ARCH_FILE, or --num-global-cond',
                file=stderr)
        exit(1)
    
    # Parameter / Arch consistency checks and fixups.
    if args.num_global_cond is not None:
        if args.num_global_cond < dset.get_max_id():
            print('Error: --num-global-cond must be >= {}, the highest ID in the dataset.'.format(
                dset.get_max_id()), file=stderr)
            exit(1)
        else:
            arch['n_gc_category'] = args.num_global_cond
    
    # Construct model
    encoder_params = config['encoder']
    bn_params = config['bottleneck'] 
    decoder_params = config['decoder'] 

    model = ae.AutoEncoder(encoder_params, bn_params, decoder_params)

    # Set CPU or GPU context

    # Restore from checkpoint
    if args.resume_step:
        pass
        print('Restored net and dset from checkpoint', file=stderr)

    # Initialize optimizer

    # Start training
    print('Starting training...', file=stderr)
    step = args.resume_step or 1
    while step < args.max_steps:

        if step % args.save_interval == 0 and step != args.resume_step:
            net_save_path = net.save(step)
            dset_save_path = dset.save(step, file_read_count)
            print('Saved checkpoints to {} and {}'.format(net_save_path, dset_save_path),
                    file=stderr)

        step += 1

if __name__ == '__main__':
    main()


