#!/usr/bin/env python
"""
The main driver program for making images of galaxies whose parameters are specified
in a configuration file.
"""

import sys
import os
import subprocess
import galsim
import yaml
import logging
import time
import copy

def merge_config(config1, config2):
    """Merge config2 into config1 sucth that it has all the information from either config1 or 
    config2 including places where both input dicts have some of a field defined.
    e.g. config1 has image.pixel_scale, and config2 has image.noise.
            Then the returned dict will have both.
    For real comflicts (the same value in both cases), config1's value takes precedence
    """
    for (key, value) in config2.items():
        if not key in config1:
            # If this key isn't in config1 yet, just add it
            config1[key] = value
        elif isinstance(value,dict) and isinstance(config1[key],dict):
            # If they both have a key, first check if the values are dicts
            # If they are, just recurse this process and merge those dicts.
            merge_config(config1[key],value)
        else:
            # Otherwise config1 takes precedence
            logger.info("Not merging key %s from the base config, since the later "
                        "one takes precedence",key)
            pass


# TODO: This is WAY too long for a single function.  Need to break it up into parts.
# Probably even put most of it into galsim/frontend.py so in can be called from 
# user python code.
def main(argv) :

    if len(argv) < 2 : 
        print 'Usage: galsim_yaml config_file'
        print 'See the example configuration files in the examples directory.'
        print 'They are the *.yaml files'
        sys.exit("No configuration file specified")

    # TODO: Should have a nice way of specifying a verbosity level...
    # Then we can just pass that verbosity into the logger.
    # Can also have the logging go to a file, etc.
    # But for now, just do a basic setup.
    logging.basicConfig(
        format="%(message)s",
        level=logging.DEBUG,
        stream=sys.stdout
    )
    logger = logging.getLogger('galsim_yaml')

    config_file = argv[1]
    logger.info('Using config file %s',config_file)

    all_config = [ c for c in yaml.load_all(open(config_file).read()) ]
    logger.info('config file successfully read in')
    #print 'all_config = ',all_config

    # If there is only 1 yaml document, then it is of course used for the configuration.
    # If there are multiple yamls documents, then the first one defines a common starting
    # point for the later documents.
    # So the configurations are taken to be:
    #   all_cong[0] + allconfig[1]
    #   all_cong[0] + allconfig[2]
    #   all_cong[0] + allconfig[3]
    #   ...

    if len(all_config) == 1:
        # If we only have 1, prepend an empty "base_config"
        all_config = [{}] + all_config

    base_config = all_config[0]

    for config in all_config[1:]:

        # Now it's safe to merge in the info from base_config
        merge_config(config,base_config)
        #print 'config = ',config

        # Read any needed input files
        nobjects = 1
        if 'input' in config :
            input = config['input']

            # Read the input catalog if provided
            if 'catalog' in input :
                catalog = input['catalog']
                file_name = catalog['file_name']
                if 'dir' in catalog:
                    dir = catalog['dir']
                    file_name = os.path.join(dir,file_name)
                input_cat = galsim.io.ReadInputCat(config,file_name)
                logger.info('Read %d objects from catalog',input_cat.nobjects)
                nobjects = input_cat.nobjects
                # Store input_cat in the config for use by BuildGSObject function.
                config['input_cat'] = input_cat

            # Read the RealGalaxy catalog if provided
            if 'real_catalog' in input :
                catalog = input['real_catalog']
                file_name = catalog['file_name']
                if 'dir' in catalog:
                    dir = catalog['dir']
                    file_name = os.path.join(dir,file_name)
                    image_dir = catalog.get('image_dir',dir)
                else:
                    image_dir = catalog.get('image_dir','.')
                real_cat = galsim.RealGalaxyCatalog(file_name, image_dir)
                logger.info('Read %d objects from catalog',real_cat.n)
                if 'preload' in catalog and catalog['preload']:
                    real_cat.preload()
                    logger.info('Preloaded the real galaxy catalog headers')
                # Store real_cat in the config for use by BuildGSObject function.
                config['real_cat'] = real_cat
 
        # We can handle not having an output field.  But it will be convenient
        # if it exists and is empty.
        if 'output' not in config :
            config['output'] = {}
        #print 'config[output] = ',config['output']
    
        # We're going to treat output as a list (for multiple file outputs if desired).
        # If it isn't a list, make it one.
        if not isinstance(config['output'],list):
            config['output'] = [ config['output'] ]
        #print 'config[output] => ',config['output']
    
        # If the output includes either data_cube or tiled_image then all images need
        # to be the same size.  We will use the first image's size for all others.
        # This just decides whether this is necessary or not.
        same_sized_images = False
        make_psf_images = False
        for output in config['output'] :
            if 'type' in output and (
                    output['type'] == 'data_cube' or output['type'] == 'tiled_image') :
                same_sized_images = True

            if 'psf' in output:
                make_psf_images = True
    
            # If the output is a tiled_image, then we can figure out nobjects from that:
            if 'type' in output and output['type'] == 'tiled_image':
                if not all (k in output for k in ['nx_tiles','ny_tiles']):
                    raise AttributeError(
                        "parameters nx_tiles and ny_tiles required for tiled_image output")
                nx_tiles = output['nx_tiles']
                ny_tiles = output['ny_tiles']
                nobjects = nx_tiles * ny_tiles

        # If specified, set the number of objects to draw.
        # Of course, nobjects might already be set above, in which case the
        # explicit value here will supersede whatever calculation we may have done.
        # And if nothing else sets nbojects, the default is nobjects=1.
        if 'nobjects' in config:
            nobjects = config['nobjects']
        logger.info('nobjects = %d',nobjects)
    
        # We'll be accessing things from the image field a lot.  So instead of constantly
        # checking "if 'image in config", we do it once and if it's not there, we just
        # make an empty dict for it.
        if 'image' not in config :
            config['image'] = {}

        # Set the size of the postage stamps if desired
        # If not set, the size will be set appropriately to enclose most of the flux.
        image_size = int(config['image'].get('size',0))
        image_xsize = int(config['image'].get('xsize',image_size))
        image_ysize = int(config['image'].get('ysize',image_size))
        if ( (image_xsize == 0) != (image_ysize == 0) ):
            raise AttributeError(
                "Both (or neither) of image.xsize and image.ysize need to be defined.")

        if not image_xsize:
            if same_sized_images:
                logger.info('All images must be the same size, so will use the automatic ' +
                            'size of the first image only')
            else:
                logger.info('Automatically sizing images')
        else:
            logger.info('Using image size = %d x %d',image_xsize,image_ysize)
    
        # Also, set the pixel scale if desired (Default is 1.0)
        pixel_scale = float(config['image'].get('pixel_scale',1.0))
        logger.info('Using pixelscale = %f',pixel_scale)


        # Build the images
        all_images = []
        all_psf_images = []
        for i in range(nobjects):
    
            t1 = time.time()

            # Initialize the random number generator we will be using.
            if 'random_seed' in config:
                rng = galsim.UniformDeviate(int(config['random_seed']+i))
            else:
                rng = galsim.UniformDeviate()
            # Store the rng in the config for use by BuildGSObject function.
            config['rng'] = rng

            fft_list = []
            phot_list = []
            psf_list = []
    
            if 'psf' in config :
                psf, safe_psf = galsim.BuildGSObject(config, 'psf')
                #print 'psf = ',psf
                fft_list.append(psf)
                phot_list.append(psf)
                psf_list.append(psf)
            else :
                safe_psf = True
            t2 = time.time()
    
            if 'pix' in config :
                pix, safe_pix = galsim.BuildGSObject(config, 'pix')
            else :
                pix = galsim.Pixel(xw=pixel_scale, yw=pixel_scale)
                safe_pix = True
            #print 'pix = ',pix
            fft_list.append(pix)
            psf_list.append(pix)
            t3 = time.time()
    
            # If the image has a WCS, we need to shear the pixel the reverse direction, so the
            # resulting WCS shear later will bring the pixel back to square.
            if 'wcs' in config['image']:
                wcs = config['image']['wcs']
                if 'shear' in wcs:
                    wcs_shear, safe_wcs = galsim.BuildShear(wcs, 'shear', rng)
                    pix.applyShear(-wcs_shear)
                else :
                    raise AttributeError("wcs must specify a shear")
        
            if 'gal' in config:
                # If we are specifying the size according to a resolution, then we 
                # need to get the PSF's half_light_radius.
                if 'resolution' in config['gal']:
                    if not 'psf' in config:
                        raise AttributeError(
                            "Cannot use gal.resolution if no psf is set.")
                    if not 'saved_re' in config['psf']:
                        raise AttributeError(
                            'Cannot use gal.resolution with psf.type = %s'%config['psf']['type'])
                    psf_re = config['psf']['saved_re']
                    resolution = config['gal']['resolution']
                    gal_re = resolution * psf_re
                    config['gal']['half_light_radius'] = gal_re

                gal, safe_gal = galsim.BuildGSObject(config, 'gal')
                #print 'gal = ',gal
                fft_list.append(gal)
                phot_list.append(gal)
            else :
                safe_gal = True
            t4 = time.time()

            # Check that we have at least gal or psf.
            if len(phot_list) == 0:
                raise AttributeError("At least one of gal or psf must be specified in config.")

            draw_method = config['image'].get('draw_method','fft')
            if draw_method == 'fft' :
                final = galsim.Convolve(fft_list)
                if 'wcs' in config['image']:
                    final.applyShear(wcs_shear)
                #print 'final = ',final
    
                if not image_xsize:
                    im = final.draw(dx=pixel_scale)
                    # If the output includes either data_cube or tiled_image then all images need
                    # to be the same size.  Use the first image's size for all others.
                    if same_sized_images :
                        image_xsize, image_ysize = im.array.shape
                else:
                    im = galsim.ImageF(image_xsize, image_ysize)
                    im.setScale(pixel_scale)
                    final.draw(im, dx=pixel_scale)

                if 'gal' in config and 'signal_to_noise' in config['gal']:
                    import math
                    import numpy
                    if 'flux' in config['gal']:
                        raise AttributeError(
                            'Only one of signal_to_noise or flux may be specified for gal')
                    if 'noise' not in config['image'] : 
                        raise AttributeError(
                            'Need to specify noise level when using gal.signal_to_noise')
                        
                    # Now determine what flux we need to get our desired S/N
                    # There are lots of definitions of S/N, but here is the one used by Great08
                    # We use a weighted integral of the flux:
                    # S = sum W(x,y) I(x,y) / sum W(x,y)
                    # N^2 = Var(S) = sum W(x,y)^2 Var(I(x,y)) / (sum W(x,y))^2
                    # Now we assume that Var(I(x,y)) is dominated by the sky noise, so
                    # Var(I(x,y)) = var
                    # We also assume that we are using a matched filter for W, so W(x,y) = I(x,y).
                    # Then a few things cancel and we find that
                    # S/N = sqrt( sum I(x,y)^2 / var )

                    # Get the variance from noise:
                    noise = config['image']['noise']
                    if not 'type' in noise :
                        raise AttributeError("noise needs a type to be specified")
                    if noise['type'] == 'Poisson' :
                        var = float(noise['sky_level']) * pixel_scale**2
                    elif noise['type'] == 'Gaussian' :
                        if 'sigma' in noise:
                            sigma = noise['sigma']
                            var = sigma * sigma
                        elif 'variance' in noise :
                            var = math.sqrt(noise['variance'])
                        else :
                            raise AttributeError(
                                "Either sigma or variance need to be specified for Gaussian noise")
                    elif noise['type'] == 'CCDNoise' :
                        var = float(noise['sky_level']) * pixel_scale**2
                        gain = float(noise.get("gain",1.0))
                        var /= gain
                        read_noise = float(noise.get("read_noise",0.0))
                        var += read_noise * read_noise
                    else :
                        raise AttributeError("Invalid type %s for noise",noise['type'])

                    if var <= 0.:
                        raise ValueError("gal.signal_to_noise requires var(noise) > 0.")
 
                    sn_meas = math.sqrt( numpy.sum(im.array**2) / var )
                    # Now we rescale the flux to get our desired S/N
                    flux = float(config['gal']['signal_to_noise']) / sn_meas
                    im *= flux
                    #print 'sn_meas = ',sn_meas,' flux = ',flux

                    if safe_gal and safe_psf and safe_pix:
                        # If the profile won't be changing, then we can store this 
                        # result for future passes.
                        config['gal']['current'] *= flux
                        config['gal']['flux'] = flux
                        del config['gal']['signal_to_noise']

            elif draw_method == 'phot' :
                final = galsim.Convolve(phot_list)
                if 'wcs' in config['image']:
                    final.applyShear(wcs_shear)
                    
                if 'signal_to_noise' in config['gal']:
                    raise NotImplementedError(
                        "gal.signal_to_noise not implemented for draw_method = phot")

                # Get the target image variance from noise:
                noise = config['image']['noise']
                if not 'type' in noise :
                    raise AttributeError("noise needs a type to be specified")
                if noise['type'] == 'Poisson' :
                    var = float(noise['sky_level']) * pixel_scale**2
                elif noise['type'] == 'Gaussian' :
                    if 'sigma' in noise:
                        sigma = noise['sigma']
                        var = sigma * sigma
                    elif 'variance' in noise :
                        var = math.sqrt(noise['variance'])
                    else :
                        raise AttributeError(
                            "Either sigma or variance need to be specified for Gaussian noise")
                elif noise['type'] == 'CCDNoise' :
                    var = float(noise['sky_level']) * pixel_scale**2
                    gain = float(noise.get("gain",1.0))
                    var /= gain
                    read_noise = float(noise.get("read_noise",0.0))
                    var += read_noise * read_noise
                else :
                    raise AttributeError("Invalid type %s for noise",noise['type'])

                if not image_xsize :
                    # TODO: Change this once issue #82 is done.
                    raise AttributeError(
                        "image size must be specified when doing photon shooting.")
                else:
                    #print 'image size = ',image_xsize,image_ysize
                    im = galsim.ImageF(image_xsize, image_ysize)
                    #print 'setScale ',pixel_scale
                    im.setScale(pixel_scale)
                    #print 'sky_level = ',var
                    #print 'drawShoot(noise = ',var/100,')'
                    #print 'before drawShoot rng() = ',rng()
                    final.drawShoot(im, noise=var/100, uniform_deviate=rng)
                    #print 'after drawShoot rng() = ',rng()
            else :
                raise AttributeError("Unknown draw_method.")
            xsize, ysize = im.array.shape

            if make_psf_images:
                final_psf = galsim.Convolve(psf_list)
                if 'wcs' in config['image']:
                    final_psf.applyShear(wcs_shear)
                # Special: if the galaxy was shifted, then also shift the psf 
                if 'shift' in config['gal']:
                    final_psf.applyShift(*config['gal']['shift']['current'])
                psf_im = galsim.ImageF(xsize,ysize)
                psf_im.setScale(pixel_scale)
                final_psf.draw(psf_im, dx=pixel_scale)
                all_psf_images += [psf_im]
            t5 = time.time()
    
            # Add noise
            if 'noise' in config['image'] : 
                noise = config['image']['noise']
                if not 'type' in noise :
                    raise AttributeError("noise needs a type to be specified")
                if noise['type'] == 'Poisson' :
                    sky_level_pixel = float(noise['sky_level']) * pixel_scale**2
                    if draw_method == 'fft':
                        im += sky_level_pixel
                        im.addNoise(galsim.CCDNoise(rng))
                        im -= sky_level_pixel
                    else:
                        # For photon shooting, galaxy already has poisson noise, so we want 
                        # to make sure not to add that again!  Just add Poisson with 
                        # mean = sky_level_pixel
                        im.addNoise(galsim.PoissonDeviate(rng, mean=sky_level_pixel))
                    #logger.info('   Added Poisson noise with sky_level = %f',sky_level)
                elif noise['type'] == 'Gaussian' :
                    if 'sigma' in noise:
                        sigma = noise['sigma']
                    elif 'variance' in noise :
                        import math
                        sigma = math.sqrt(noise['variance'])
                    else :
                        raise AttributeError(
                            "Either sigma or variance need to be specified for Gaussian noise")
                    im.addNoise(galsim.GaussianDeviate(rng,sigma=sigma))
                    #logger.info('   Added Gaussian noise with sigma = %f',sigma)
                elif noise['type'] == 'CCDNoise' :
                    sky_level_pixel = float(noise['sky_level']) * pixel_scale**2
                    gain = float(noise.get("gain",1.0))
                    read_noise = float(noise.get("read_noise",0.0))
                    if draw_method == 'fft':
                        im += sky_level_pixel
                        im.addNoise(galsim.CCDNoise(rng, gain=gain, read_noise=read_noise))
                        im -= sky_level_pixel
                    else:
                        # For photon shooting, galaxy already has poisson noise, so we want 
                        # to make sure not to add that again!
                        im *= gain
                        im.addNoise(galsim.PoissonDeviate(rng, mean=sky_level_pixel*gain))
                        im /= gain
                        im.addNoise(galsim.GaussianDeviate(rng, sigma=read_noise))
                    #logger.info('   Added CCD noise with sky_level = %f, ' +
                                #'gain = %f, read_noise = %f',sky_level,gain,read_noise)
                else :
                    raise AttributeError("Invalid type %s for noise",noise['type'])
            t6 = time.time()
    
            # Store that into the list of all images
            all_images += [im]
            t7 = time.time()
    
            #logger.info('   Times: %f, %f, %f, %f, %f, %f', t2-t1, t3-t2, t4-t3, t5-t4, t6-t5, t7-t6)
            logger.info('Image %d: size = %d x %d, total time = %f sec', i, xsize, ysize, t7-t1)
    
        logger.info('Done making images of galaxies')
    
        # Now write the image to disk.
        # Loop over all output formats:
        for output in config['output'] :
            #print 'output = ',output
    
            # Get the file_name
            if 'file_name' in output :
                file_name = output['file_name']
            else :
                # If a file_name isn't specified, we use the name of the calling script to
                # generate a fits file name.
                import inspect
                script_name = os.path.basiename(
                    inspect.getfile(inspect.currentframe())) # script filename (usually with path)
                # Strip off a final suffix if present.
                file_name = os.path.splitext(script_name)[0]
                logger.info('No output file name specified.  Using %s',file_name)
            #print 'file_name = ',file_name

            # Prepend a dir to the beginning of the filename if requested.
            if 'dir' in output :
                if not os.path.isdir(output['dir']) :
                    os.mkdir(output['dir'])
                file_name = os.path.join(output['dir'],file_name)
    
            if 'psf' in output:
                psf_file_name = None
                output_psf = output['psf']
                if 'file_name' in output_psf:
                    psf_file_name = output_psf['file_name']
                    if 'dir' in output:
                        psf_file_name = os.path.join(output['dir'],psf_file_name)
                else:
                    raise NotImplementedError(
                        "Only the file_name version of psf output is currently implemented.")
    
            # Each kind of output works slightly differently
            if nobjects != 1:
                if not 'type' in output:
                    raise AttributeError(
                        "output type is required when there are multiple images drawn.")
                output_type = output['type']
                #print 'type = ',output_type

            if nobjects == 1:
                all_images[0].write(file_name, clobber=True)
                logger.info('Wrote image to fits file %r',file_name)
                if 'psf' in output:
                    if psf_file_name:
                        all_psf_images[0].write(psf_file_name, clobber=True)
                        logger.info('Wrote psf image to fits file %r',psf_file_name)
            elif output_type == 'multi_fits' :
                galsim.fits.writeMulti(all_images, file_name, clobber=True)
                logger.info('Wrote images to multi-extension fits file %r',file_name)
                if 'psf' in output:
                    if psf_file_name:
                        galsim.fits.writeMulti(all_psf_images, psf_file_name, clobber=True)
                        logger.info('Wrote psf images to multi-extension fits file %r',
                                    psf_file_name)
                    else:
                        raise AttributeError(
                            "Only the file_name version of psf output is possible with multi_fits")
            elif output_type == 'data_cube' :
                galsim.fits.writeCube(all_images, file_name, clobber=True)
                logger.info('Wrote image to fits data cube %r',file_name)
                if 'psf' in output:
                    if psf_file_name:
                        galsim.fits.writeCube(all_psf_images, psf_file_name, clobber=True)
                        logger.info('Wrote psf images to fits data cube %r',psf_file_name)
            elif output_type == 'tiled_image' :
                if not all (k in output for k in ['nx_tiles','ny_tiles']):
                    raise AttributeError(
                        "parameters nx_tiles and ny_tiles required for tiled_image output")
                nx_tiles = output['nx_tiles']
                ny_tiles = output['ny_tiles']
                border = output.get("border",0)
                xborder = output.get("xborder",border)
                yborder = output.get("yborder",border)
                full_xsize = (image_xsize + xborder) * nx_tiles - xborder
                full_ysize = (image_ysize + yborder) * ny_tiles - yborder
                full_image = galsim.ImageF(full_xsize,full_ysize)
                full_image.setScale(pixel_scale)
                if 'psf' in output:
                    full_psf_image = galsim.ImageF(full_xsize,full_ysize)
                    full_psf_image.setScale(pixel_scale)
                k = 0
                for ix in range(nx_tiles):
                    for iy in range(ny_tiles):
                        if k < len(all_images):
                            xmin = ix * (image_xsize + xborder) + 1
                            xmax = xmin + image_xsize-1
                            ymin = iy * (image_ysize + yborder) + 1
                            ymax = ymin + image_ysize-1
                            b = galsim.BoundsI(xmin,xmax,ymin,ymax)
                            full_image[b] = all_images[k]
                            if 'psf' in output:
                                full_psf_image[b] = all_psf_images[k]
                            k = k+1
                full_image.write(file_name, clobber=True)
                logger.info('Wrote tiled image to fits file %r',file_name)
                if 'psf' in output:
                    if psf_file_name:
                        full_psf_image.write(psf_file_name, clobber=True)
                        logger.info('Wrote tled psf images to fits file %r',psf_file_name)
            else :
                raise AttributeError("Invalid type for output: %s",output_type)

    
if __name__ == "__main__":
    main(sys.argv)
