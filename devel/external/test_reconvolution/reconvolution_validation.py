import os
import pdb
import pyfits
import logging
import sys
import numpy
import sys
import math
import pylab
import argparse
import yaml
import galsim
import copy

HSM_ERROR_VALUE = -99
NO_PSF_VALUE    = -98

def _ErrorResults(ERROR_VALUE,ident):

    result = {  'moments_g1' : ERROR_VALUE,
                        'moments_g2' : ERROR_VALUE,
                        'hsmcorr_g1' : ERROR_VALUE,
                        'hsmcorr_g2' : ERROR_VALUE,
                        'moments_sigma' : ERROR_VALUE,
                        'hsmcorr_sigma' : ERROR_VALUE,
                        'moments_g1err' : ERROR_VALUE,
                        'moments_g2err' : ERROR_VALUE,
                        'hsmcorr_g1err' : ERROR_VALUE,
                        'hsmcorr_g2err' : ERROR_VALUE,
                        'moments_sigmaerr' : ERROR_VALUE,
                        'hsmcorr_sigmaerr' : ERROR_VALUE,
                        'ident' : ident }

    return result

def WriteResultsHeader(file_output):
    """
    @brief Writes a header file for results.
    @param file_output  file pointer to be written into
    """
    
    output_header = '# id ' + 'G1_moments G2_moments G1_hsmcorr G2_hsmcorr ' + \
                              'moments_sigma hsmcorr_sigma ' + \
                              'err_g1obs err_g2obs err_g1hsm err_g2hsm err_sigma err_sigma_hsm' + \
                              '\n'
    file_output.write(output_header) 

def WriteResults(file_output,results):
    """
    #brief Save results to file.
    
    @file_output            file pointer to which results will be written
    @results                dict - result of GetResultsPhoton or GetResultsFFT
    """ 

    output_row_fmt = '%d\t' + '% 2.8e\t'*6 + '\n'

    # loop over the results items
       
    file_output.write(output_row_fmt % (
            results['ident'] ,
            results['moments_g1'] ,
            results['moments_g2'] ,
            results['hsmcorr_g1'] ,
            results['hsmcorr_g2'] ,
            results['moments_sigma'] ,
            results['hsmcorr_sigma'] 
        )) 

def CreateRGC(config):
    """
    Creates a mock real galaxy catalog and saves it to file.
    Arguments
    ---------
    config              main config dict
    """

    # set up the config accordingly
    cosmos_config = copy.deepcopy(config['cosmos_images']);
    cosmos_config['image']['gsparams'] = copy.deepcopy(config['gsparams'])

    # process the config and create fits file
    try:
        galsim.config.Process(cosmos_config,logger=None)
        logger.debug('created RGC images')
    except Exception,e:
        logger.error('failed to build RGC images, message %s' % e)
    # this is a hack - there should be a better way to get this number
    n_gals = len(galsim.config.GetNObjForMultiFits(cosmos_config,0,0))
    logger.info('building real galaxy catalog with %d galaxies' % n_gals)

    # get the file names for the catalog, image and PSF RGC
    filename_gals = os.path.join(config['cosmos_images']['output']['dir'],
        config['cosmos_images']['output']['file_name'])
    filename_psfs = os.path.join(config['cosmos_images']['output']['dir'],
        config['cosmos_images']['output']['psf']['file_name'])
    filename_rgc = os.path.join(
        config['reconvolved_images']['input']['real_catalog']['dir'],
        config['reconvolved_images']['input']['real_catalog']['file_name'])

    # get some additional parameters to put in the catalog
    pixel_scale = config['cosmos_images']['image']['pixel_scale']
    noise_var = config['cosmos_images']['image']['noise']['variance']
    BAND = 'F814W'     # copied from example RGC
    MAG  = 20          # no idea if this is right
    WEIGHT = 10        # ditto

    # get the columns of the catalog
    columns = []
    columns.append( pyfits.Column( name='IDENT'         ,format='J'  ,array=range(0,n_gals)       ))    
    columns.append( pyfits.Column( name='MAG'           ,format='D'  ,array=[MAG] * n_gals        ))
    columns.append( pyfits.Column( name='BAND'          ,format='5A' ,array=[BAND] * n_gals       ))    
    columns.append( pyfits.Column( name='WEIGHT'        ,format='D'  ,array=[WEIGHT] * n_gals     ))    
    columns.append( pyfits.Column( name='GAL_FILENAME'  ,format='23A',array=[filename_gals]*n_gals))            
    columns.append( pyfits.Column( name='PSF_FILENAME'  ,format='27A',array=[filename_psfs]*n_gals))            
    columns.append( pyfits.Column( name='GAL_HDU'       ,format='J'  ,array=range(0,n_gals)       ))    
    columns.append( pyfits.Column( name='PSF_HDU'       ,format='J'  ,array=range(0,n_gals)       ))    
    columns.append( pyfits.Column( name='PIXEL_SCALE'   ,format='D'  ,array=[pixel_scale] * n_gals))        
    columns.append( pyfits.Column( name='NOISE_MEAN'    ,format='D'  ,array=[0] * n_gals          ))
    columns.append( pyfits.Column( name='NOISE_VARIANCE',format='D'  ,array=[noise_var] * n_gals  ))        

    # create table
    hdu_table = pyfits.new_table(columns)
    
    # save all catalogs
    hdu_table.writeto(filename_rgc,clobber=True)
    logger.info('saved real galaxy catalog %s' % filename_rgc)

    # if in debug mode, save some plots
    if config['args'].debug : SavePreviewRGC(config,filename_rgc)

def SavePreviewRGC(config,filename_rgc,n_gals_preview=10):
    """
    Function for eyeballing the contents of the created mock RGC catalogs.
    Arguments
    ---------
    config              config dict 
    filename_rgc        filename of the newly created real galaxy catalog fits 
    """

    # open the RGC
    table = pyfits.open(filename_rgc)[1].data

    # get the image and PSF filenames
    fits_gal = table[0]['GAL_FILENAME']
    fits_psf = table[0]['PSF_FILENAME']
    import pylab

    # loop over galaxies and save plots
    for n in range(n_gals_preview):

        img_gal = pyfits.getdata(fits_gal,ext=n)
        img_psf = pyfits.getdata(fits_psf,ext=n)

        pylab.subplot(1,2,1)
        pylab.imshow(img_gal,interpolation='nearest')
        pylab.title('galaxy')
        
        pylab.subplot(1,2,2)
        pylab.imshow(img_psf,interpolation='nearest')
        pylab.title('PSF')
        
        filename_fig = 'fig.previewRGC.%s.%d.png' % (config['args'].filename_config,n)

        pylab.savefig(filename_fig)


def GetReconvImage(config):
    """
    Gets an image of the mock ground observation using a reconvolved method, using 
    an existing real galaxy catalog. Function CreateRGC(config) must be called earlier.
    Arguments
    ---------
    config          main config dict read by yaml

    Returns a tuple img_gals,img_psfs, which are stripes of postage stamps.
    """

    # adjust the config for the reconvolved galaxies
    reconv_config = copy.deepcopy(config['reconvolved_images'])
    reconv_config['image']['gsparams'] = copy.deepcopy(config['gsparams'])
    reconv_config['input']['catalog'] = copy.deepcopy(config['cosmos_images']['input']['catalog'])
    reconv_config['gal']['shift'] = copy.deepcopy(config['cosmos_images']['gal']['shift'])

    # process the input before BuildImage    
    galsim.config.ProcessInput(reconv_config)
    # get the reconvolved galaxies
    img_gals,img_psfs,_,_ = galsim.config.BuildImage(config=reconv_config,make_psf_image=True)

    return (img_gals,img_psfs)

def GetDirectImage(config):
    """
    Gets an image of the mock ground observation using a direct method, without reconvolution.
    Arguments
    ---------
    config          main config dict read by yaml

    Returns a tuple img_gals,img_psfs, which are stripes of postage stamps
    """

    # adjust the config
    direct_config = copy.deepcopy(config['reconvolved_images'])
    direct_config['image']['gsparams'] = copy.deepcopy(config['gsparams'])
    # switch gals to the original cosmos gals
    direct_config['gal'] = copy.deepcopy(config['cosmos_images']['gal'])  
    direct_config['gal']['flux'] = 1.
    # delete signal to noise - we want the direct images to be of best possible quality
    del direct_config['gal']['signal_to_noise'] 
    direct_config['gal']['shear'] = copy.deepcopy(config['reconvolved_images']['gal']['shear'])  
    direct_config['input'] = copy.deepcopy(config['cosmos_images']['input'])
    
    # process the input before BuildImage     
    galsim.config.ProcessInput(direct_config)
    # get the direct galaxies
    img_gals,img_psfs,_,_ = galsim.config.BuildImage(config=direct_config,make_psf_image=True)

    return (img_gals,img_psfs)

def GetShapeMeasurements(image_gal, image_psf, ident=-1):
    """
    @param image_gal    galsim image of the galaxy
    @param image_psf    galsim image of the PSF
    @param ident        id of the galaxy (default -1)
    """

    HSM_SHEAR_EST = "KSB"
    NO_PSF_VALUE = -10

    # find adaptive moments  
    try: moments = galsim.FindAdaptiveMom(image_gal)
    except: raise RuntimeError('FindAdaptiveMom error')
        

    # find HSM moments
    if image_psf == None: hsmcorr_phot_e1 =  hsmcorr_phot_e2  = NO_PSF_VALUE 
    else:
        try: 
            hsmcorr   = galsim.EstimateShearHSM(image_gal,image_psf,strict=True,  
                                                                       shear_est=HSM_SHEAR_EST)
        except: raise RuntimeError('EstimateShearHSM error')
                
        logger.debug('galaxy %d : adaptive moments G1=% 2.6f\tG2=% 2.6f\tsigma=%2.6f\t hsm \
            corrected moments G1=% 2.6f\tG2=% 2.6f' 
            % ( ident , moments.observed_shape.g1 , moments.observed_shape.g2 , 
                moments.moments_sigma , hsmcorr.corrected_g1,hsmcorr.corrected_g2) )

        # create the output dictionary
        result = {  'moments_g1' : moments.observed_shape.g1,
                    'moments_g2' : moments.observed_shape.g2,
                    'hsmcorr_g1' : hsmcorr.corrected_g1,
                    'hsmcorr_g2' : hsmcorr.corrected_g2,
                    'moments_sigma' :  moments.moments_sigma, 
                    'hsmcorr_sigma' :  hsmcorr.moments_sigma, 
                    'ident' : ident}
        
    return result

def GetPixelDifference(image1,image2,id):
    """
    Returns ratio of maximum pixel difference of two images 
    to the value of the maximum of pixels in the first image.
    Normalises the fluxes to one before comparing.
    Arguments
    ---------
    image1
    image2      images to compare
    
    Return a dict with fields: 
    diff        the difference of interest
    ident       id provided earlier
    """

    # get the normalised images
    img1_norm = image1.array/sum(image1.array.flatten())
    img2_norm = image2.array/sum(image2.array.flatten())
    # create a residual image
    diff_image = img1_norm - img2_norm
    # calculate the ratio
    max_diff_over_max_image = abs(diff_image.flatten()).max()/img1_norm.flatten().max()
    logger.debug('max(residual) / max(image1) = %2.4e ' % ( max_diff_over_max_image )  )
    return { 'diff' : max_diff_over_max_image, 'ident' :id }


def RunMeasurement(config,filename_results,mode):
    """
    @brief              Run the comparison of reconvolved and direct imageing.
    @param config       main config dict read by yaml
    @param mode         direct or reconv
    """

    file_results = open(filename_results,'w')
    WriteResultsHeader(file_results)

    # first create the RGC
    if mode == 'reconv':
        try:
            CreateRGC(config)
        except Exception,e:
            raise ValueError('creating RGC failed, message: %s ' % e)
        image_fun = GetReconvImage
    elif mode == 'direct':
        image_fun = GetDirectImage
    else: raise ValueError('unknown mode %s - should be either reconv or direct' % mode)


    # try:
    logger.info('building %s image' , mode)
    (img_gals,img_psfs) = image_fun(config)
    # except Exception,e:
    # logging.error('building image failed, message: %s' % e)

    # get image size
    npix = config['reconvolved_images']['image']['stamp_size']
    nobjects = galsim.config.GetNObjForImage(config['reconvolved_images'],0)

    # loop over objects
    for i in range(nobjects):

        # cut out stamps
        img_gal =  img_gals[ galsim.BoundsI(  1 ,   npix, i*npix+1, (i+1)*npix ) ]
        img_psf =  img_psfs[ galsim.BoundsI(  1 ,   npix, i*npix+1, (i+1)*npix ) ]
 
        # get shapes and pixel differences
        try:
            result = GetShapeMeasurements(img_gal, img_psf, i)
        except Exception,e:
            logger.error('failed to get shapes for for galaxy %d. Message:\n %s' % (i,e))
            result = _ErrorResults(HSM_ERROR_VALUE,i)
  
        WriteResults(file_results,result)

    file_results.close()

def ChangeConfigValue(config,path,value):
    """
    Changes the value of a variable in nested dict config to value.
    The field in the dict-list structure is identified by a list path.
    Example: to change the following field in config dict to value:
    conf['lvl1'][0]['lvl3']
    use the follwing path=['lvl1',0,'lvl2']
    Arguments
    ---------
        config      an object with dicts and lists
        path        a list of strings and integers, pointing to the field in config that should
                    be changed, see Example above
        Value       new value for this field
    """

    # build a string with the dictionary path
    eval_str = 'config'
    for key in path: 
        # check if path element is a string addressing a dict
        if isinstance(key,str):
            eval_str += '[\'' + key + '\']'
        # check if path element is an integer addressing a list
        elif isinstance(key,int):
            eval_str += '[' + str(key) + ']'
        else: 
            raise ValueError('element in the config path should be either string or int, is %s' 
                % str(type(key)))
    # assign the new value
    try:
        exec(eval_str + '=' + str(value))
        logging.debug('changed %s to %f' % (eval_str,eval(eval_str)))
    except:
        print config
        raise ValueError('wrong path in config : %s' % eval_str)

def RunComparisonForVariedParams(config):
    """
    Runs the comparison of direct and reconv convolution methods, producing results file for each of the 
    varied parameters in the config file, under key 'vary_params'.
    Produces a results file for each parameter and it's distinct value.
    The filename of the results file is: 'results.yaml_filename.param_name.param_value_index.cat'
    Arguments
    ---------
    config              the config object, as read by yaml
    """

    # loop over parameters to vary
    for param_name in config['vary_params'].keys():

        # get more info for the parmaeter
        param = config['vary_params'][param_name]
        
        # loop over all values of the parameter, which will be changed
        for iv,value in enumerate(param['values']):
            
            # copy the config to the original
            changed_config = copy.deepcopy(config)
            
            # perform the change
            ChangeConfigValue(changed_config,param['path'],value)
            logging.info('changed parameter %s to %s' % (param_name,str(value)))

            # If the setting change affected reconv image, then rebuild it
            if param['rebuild_reconv'] :
                logger.info('getting reconv results')
                changed_config_reconv = copy.deepcopy(changed_config)
                # Get the results filenames
                filename_results_reconv = 'results.%s.%s.%03d.reconv.cat' % (
                                        config['args'].filename_config, param_name,iv)
                
                # Run and save the measurements
                RunMeasurement(changed_config_reconv,filename_results_reconv,'reconv')             
                logging.info(('saved reconv results for varied parameter %s with value %s\n'
                     + 'filename: %s') % (param_name,str(value),filename_results_reconv) )

            # If the setting change affected direct image, then rebuild it           
            if param['rebuild_direct'] :
                logger.info('getting direct results')
                changed_config_direct = copy.deepcopy(changed_config)
                # Get the results filename
                filename_results_direct = 'results.%s.%s.%03d.direct.cat' % (
                    config['args'].filename_config,param_name,iv)

                # Run the measurement
                RunMeasurement(changed_config_direct,filename_results_direct,'direct')
                logging.info(('saved direct results for varied parameter %s with value %s\n'  
                    + 'filename %s') % ( param_name,str(value),filename_results_direct) )




if __name__ == "__main__":

    description = 'Compare reconvolved and directly created galaxies.'

    # parse arguments
    parser = argparse.ArgumentParser(description=description, add_help=True)
    parser.add_argument('filepath_config', type=str,
                 help='yaml config file, see reconvolution_validation.yaml for example.')
    parser.add_argument('--debug', action="store_true", help='run in debug mode', default=False)
    parser.add_argument('--default_only', action="store_true", 
        help='Run only for default settings, ignore vary_params in config file.\
              --vary_params_only must not be used alongside this option.'
        , default=False)
    parser.add_argument('--vary_params_only', action="store_true", 
        help='Run only for varied settings, do not run the defaults.\
               --default_only must not be used alongside this option.'
        , default=False)
    
    args = parser.parse_args()
    args.filename_config = os.path.basename(args.filepath_config)

    # set up logger
    if args.debug: logger_level = 'logging.DEBUG'
    else:  logger_level = 'logging.INFO'
    logging.basicConfig(format="%(message)s", level=eval(logger_level), stream=sys.stdout)
    logger = logging.getLogger("photon_vs_fft") 

    # sanity check the inputs
    if args.default_only and args.vary_params_only:
        raise('Use either default_only or vary_params_only, or neither.')

    # load the configuration file
    config = yaml.load(open(args.filename_config,'r'))
    config['args'] = args
   
    # set flags what to do
    if args.vary_params_only:
        config['run_default'] = False
        config['run_vary_params'] = True
    elif args.default_only:
        config['run_default'] = True
        config['run_vary_params'] = False
    else:
        config['run_default'] = True
        config['run_vary_params'] = True

    # run only the default settings
    if config['run_default']:
        logger.info('running reconv and direct for default settings')
        # Get the results filenames
        
        filename_results_direct = 'results.%s.default.direct.cat' % (config['args'].filename_config)
        filename_results_reconv = 'results.%s.default.reconv.cat' % (config['args'].filename_config)
        
        config_direct = copy.deepcopy(config)
        RunMeasurement(config_direct,filename_results_direct,'direct')
        config_reconv = copy.deepcopy(config)
        RunMeasurement(config_reconv,filename_results_reconv,'reconv')
        
        logging.info(('saved direct and reconv results for default parameter set\n'
             + 'filenames: %s\t%s') % (filename_results_direct,filename_results_reconv))
    
    # run the config including changing of the parameters
    if config['run_vary_params']:
        logger.info('running reconvolution validation for varied parameters')
        RunComparisonForVariedParams(config)


