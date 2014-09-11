#!/usr/bin/env python
""" Defines the synthetic_image class to add image realism to the idealized sunrise images.

The synthetic_image class defines a number of routines to take the original image and 
convolve it with some psf function, add sky noise, rebin to an appropate pixel scale 
(based on telescope), scale to an approparte image size (based on a petrosian radius 
calculation, and add background image (SDSS only supported at the moment).


The majority of the code in this file was developed by Greg Snyder.


"""
import numpy as np
import os
import sys
import math
import astropy.io.fits as fits
import cosmocalc
import pyfits
import scipy as sp
import scipy.ndimage
import scipy.signal
import congrid
import sunpy.sunpy__load
#import matplotlib.pyplot as plt
import time

__author__ = "Paul Torrey and Greg Snyder"
__copyright__ = "Copyright 2014, The Authors"
__credits__ = ["Paul Torrey", "Greg Snyder"]
__license__ = "GPL"
__version__ = "1.0"
__maintainer__ = "Paul Torrey"
__email__ = "ptorrey@mit.harvard.edu"
__status__ = "Production"
if __name__ == '__main__':    #code to execute if called from command-line
    pass    #do nothing 



# DEFINE SOME UNITS
abs_dist        = 0.01          # 10 pc in units of kpc
erg_per_joule   = 1e7
speedoflight_m  = 2.99e8
m2_to_cm2       = 1.0e-4
n_arcsec_per_str = 4.255e10             # (radian per arc second)^2
n_pixels_galaxy_zoo = 424 


####################################################################################################################################################
# background images created by Greg Snyder on 6/18/14
# background obtained from:  data.sdss3.org/mosaics
# Ra = 175.0
# Dec = 30.0
# Size (deg) = 0.5
# Pixel Scale = 0.24 "/pixel
#
# background images do not exist (here) for non-SDSS bands.
# To add them, a large fits file with similar readability 
# needs to be created with the image units in nanomaggies (if to be compatible with current framework).
#

backgrounds = [	[], [], 
			['/n/ghernquist/ptorrey/Illustris/IllustrisImagePipeline/SDSS_backgrounds/J113959.99+300000.0-u.fits'], 	# SDSS-u
			['/n/ghernquist/ptorrey/Illustris/IllustrisImagePipeline/SDSS_backgrounds/J113959.99+300000.0-g.fits'], 	# SDSS-g
			['/n/ghernquist/ptorrey/Illustris/IllustrisImagePipeline/SDSS_backgrounds/J113959.99+300000.0-r.fits'], 	# SDSS-r
			['/n/ghernquist/ptorrey/Illustris/IllustrisImagePipeline/SDSS_backgrounds/J113959.99+300000.0-i.fits'], 	# SDSS-i
			['/n/ghernquist/ptorrey/Illustris/IllustrisImagePipeline/SDSS_backgrounds/J113959.99+300000.0-z.fits'], 	# SDSS-z
		[], [], [], 
		[], [], [], [], [], [], [], [], [], [],
		[], [], [], [], [], [], [], [], [], [],
		[], [], [], [], [], []		]
######################################################################################################################################################


#== Basic routine to build a synthetic image from a SUNRISE fits file and return the image to the user
def build_synthetic_image(filename, band, r_petro_kpc=None, seed=None, camera=0, psf_fwhm_arcsec=None, include_background=True):
    obj     	 = synthetic_image(filename, band=band, r_petro_kpc=r_petro_kpc, seed=seed, camera=camera, psf_fwhm_arcsec=psf_fwhm_arcsec, include_background=include_background )
    return_image = obj.bg_image.return_image()
    return_rp    = obj.r_petro_kpc

    return return_image, return_rp


#=====================================================#
# single_image class:
# 
# This class is used to host and track the properties for 
# a single image (one galaxy, one band, one level of realism).
# This class tracks important image traits, such as the 
# image array itself, the field of view, number of pixels,
# ab_zeropoint, pixel scale, etc.
# 
# When new images are created (e.g., when psf bluring is 
# done on the original image) a new "single_image" instance 
# is created.  
#
# The synthetic_image class (defined below) contains 
# several instances of this single_image class
#
#=====================================================#
class single_image:
    def __init__(self):
	self.image_exists = False

    def init_image(self, image, parent_obj, fov=None):	
        self.image 		= image
        self.n_pixels 		= image.shape[0] 
	if fov==None:
            self.pixel_in_kpc    	= parent_obj.param_header.get('linear_fov') / self.n_pixels
	else:
	    self.pixel_in_kpc 		= fov / self.n_pixels
        self.pixel_in_arcsec 	= self.pixel_in_kpc / parent_obj.cosmology.kpc_per_arcsec
	self.image_exists	= True
	self.camera_pixel_in_arcsec = (self.pixel_in_kpc / parent_obj.param_header.get('cameradist') ) * 2.06e5
	self.calc_ab_abs_zero(parent_obj)
	self.convert_to_nanomaggies(parent_obj)

    def calc_ab_abs_zero(self, parent_obj):
	lambda_eff_in_m         = parent_obj.lambda_eff
        pixel_area_in_str       = self.camera_pixel_in_arcsec**2 / n_arcsec_per_str
        cameradist_in_kpc       = parent_obj.param_header.get('cameradist')

        to_nu                     = ((lambda_eff_in_m**2 ) / (speedoflight_m))* pixel_area_in_str
        to_microjanskies          = (1.0e6) * to_nu * (1.0e26)                                          # 1 Jy = 1e-26 W/m^2/Hz
        to_microjanskies_at_10pc  = to_microjanskies * (cameradist_in_kpc / abs_dist)**2                # distances are in kpc 

        ab_abs_zeropoint = 23.90 - (2.5*np.log10(to_microjanskies_at_10pc))             # should go into self structure
	self.ab_abs_zeropoint = ab_abs_zeropoint

    def convert_to_nanomaggies(self, parent_obj):
	distance_factor = (10.0 / (parent_obj.cosmology.lum_dist * 1.0e6))**2
	orig_to_nmaggies = distance_factor * 10.0**(0.4*(22.5 - self.ab_abs_zeropoint) ) 
	self.image_in_nmaggies = self.image * orig_to_nmaggies

    def return_image(self):
	return self.image

#============ COSMOLOGY PARAMETERS =====================#
# cosmology class:
#
#  used to track (i) the cosmological parameters and 
#  (ii) image properties set by our adopted cosmology
#
#  This class is used to distinguish features of the telescope
#  (e.g., pixel size in arcseconds) from features of our 
# adopted cosmology (e.g.,image kpc per arcsec)
#
#=======================================================#
class cosmology:
    def __init__(self, redshift, H0=70.4, WM=0.2726, WV=0.7274):
	self.H0=H0
	self.WM=WM
	self.WV=WV
	self.redshift = redshift
        self.lum_dist       = (cosmocalc.cosmocalc(self.redshift, H0=self.H0, WM=self.WM, WV=self.WV))['DL_Mpc']          ## luminosity dist in mpc
        self.ang_diam_dist  = (cosmocalc.cosmocalc(self.redshift, H0=self.H0, WM=self.WM, WV=self.WV))['DA_Mpc']          ## 
        self.kpc_per_arcsec = (cosmocalc.cosmocalc(self.redshift, H0=self.H0, WM=self.WM, WV=self.WV))['PS_kpc']






#============ TELESCOPE PARAMETERS =====================#
# telescope class:
#
# used to track the psf size in arcsec and pixelsize in arcsec
#=======================================================#
class telescope:
    def __init__(self, psf_fwhm_arcsec, pixelsize_arcsec):
	self.psf_fwhm_arcsec  = psf_fwhm_arcsec 
	self.pixelsize_arcsec = pixelsize_arcsec






#=============SYNTHETIC_IMAGE CLAS======================#
# synthetic_image:
# 
# This is the main class of the routine, which is used to 
# load a sunrise generated broadband.fits file and 
# add all the image realism needed to make even handed 
# comparisons with SDSS images.
#=======================================================#
class synthetic_image:
    def __init__(self, filename, band=0, camera=0, redshift=0.05, psf_fwhm_arcsec=None, pixelsize_arcsec=0.24, r_petro_kpc=None, save_fits=True, seed=None, include_background=True):
        if (not os.path.exists(filename)):
            print "file not found:", filename
            sys.exit()

	if psf_fwhm_arcsec==None:
	    psf_fwhm_arcsec=1.0

	start_time = time.time()
	self.filename = filename
	self.cosmology = cosmology(redshift)
	self.telescope = telescope(psf_fwhm_arcsec, pixelsize_arcsec)

#============ DO THE READING ===========================#
        band_names  = sunpy.sunpy__load.load_broadband_names(filename)
        hdulist = fits.open(filename)
	
        if type(band) is not int:
            band = (((band_names == band).nonzero())[0])[0]

	self.band	      = band
        self.band_name        = band_names[band]
        self.image_header     = hdulist['CAMERA'+str(camera)+'-BROADBAND-NONSCATTER'].header
        self.broadband_header = hdulist['BROADBAND'].header
        self.param_header     = hdulist['CAMERA'+str(camera)+'-PARAMETERS'].header
        self.int_quant_data   = hdulist['INTEGRATED_QUANTITIES'].data
        self.filter_data      = hdulist['FILTERS'].data
        self.lambda_eff       = (self.filter_data['lambda_eff'])[band]
        hdulist.close()
#============= DECLARE ALL IMAGES HERE =================#
	self.sunrise_image  = single_image()		# orig sunrise image
	self.psf_image      = single_image()		# supersampled image + psf convolution 
	self.rebinned_image = single_image()		# rebinned by appropriate pixel scale
	self.noisy_image    = single_image()		# noise added via gaussian draw
	self.nmag_image     = single_image()		# converted to nanomaggies units
	self.rp_image       = single_image()		# scale image based on rp radius criteria (for GZ)
	self.bg_image	    = single_image()		# add backgrounds (only possible for 5 SDSS bands at the moment)
#============ SET ORIGINAL IMAGE ======================#
	all_images  = sunpy.sunpy__load.load_all_broadband_images(filename,camera=camera)
	self.sunrise_image.init_image(all_images[band,:,:], self) 

	self.add_gaussian_psf()
	self.rebin_to_physical_scale()
	self.add_noise()
	self.calc_r_petro(r_petro_kpc=r_petro_kpc)
	self.resize_image_from_rp()
	self.add_background(seed=seed, include_background=include_background)
	end_time   = time.time()
	print "init images + adding realism took "+str(end_time - start_time)+" seconds"

	if save_fits:
	    orig_dir=filename[:filename.index('broadband')]
	    outputfitsfile = orig_dir+'synthetic_image_'+filename[filename.index('broadband_')+10:filename.index('.fits')]+'_band_'+str(self.band)+'_camera_'+str(camera)+'.fits'
	    self.save_bgimage_fits(outputfitsfile)


    def add_gaussian_psf(self, sample_factor=1.0):		# operates on sunrise_image -> creates psf_image
	current_psf_sigma_pixels = self.telescope.psf_fwhm_arcsec * (1.0/2.355) / self.sunrise_image.pixel_in_arcsec

	if current_psf_sigma_pixels<8:				# want the psf sigma to be resolved with (at least) 8 pixels...
	    target_psf_sigma_pixels  = 8.0
	    n_pixel_new = np.floor(self.sunrise_image.n_pixels * target_psf_sigma_pixels / current_psf_sigma_pixels )

	    if n_pixel_new > 2500:		# an arbitrary upper limit owing to memory constraints.  Beyond this, the PSF is already very small...
		n_pixel_new = 2500
		target_psf_sigma_pixels = n_pixel_new * current_psf_sigma_pixels / self.sunrise_image.n_pixels

	    new_image = congrid.congrid(self.sunrise_image.image,  (n_pixel_new, n_pixel_new) )
	    current_psf_sigma_pixels = target_psf_sigma_pixels * ((self.sunrise_image.n_pixels * target_psf_sigma_pixels / current_psf_sigma_pixels) / n_pixel_new )
	else:
	    new_image = self.sunrise_image.image

	psf_image = np.zeros_like( new_image ) * 1.0
	dummy = sp.ndimage.filters.gaussian_filter(new_image, current_psf_sigma_pixels, output=psf_image, mode='constant')

	self.psf_image.init_image(psf_image, self) #self.param_header.get('linear_fov'), self.cosmology.kpc_per_arcsec)


    def rebin_to_physical_scale(self, verbose=False):		# operates on psf_image -> creates rebinned_image
	n_pixel_new = np.floor( ( self.psf_image.pixel_in_arcsec / self.telescope.pixelsize_arcsec )  * self.psf_image.n_pixels )
	rebinned_image = congrid.congrid(self.psf_image.image,  (n_pixel_new, n_pixel_new) )

	self.rebinned_image.init_image(rebinned_image, self) 


    def add_noise(self, sn_limit=25.0):				# operates on rebinned_image -> creates noisy_image
	total_flux 	= np.sum( self.rebinned_image.image )
	area 		= 1.0 * self.rebinned_image.n_pixels * self.rebinned_image.n_pixels
	sky_sig 	= np.sqrt( (total_flux / sn_limit)**2 / (area**2 ) )
	noise_image 	= 0.0 * sky_sig * np.random.randn( self.rebinned_image.n_pixels, self.rebinned_image.n_pixels )

	self.noisy_image.init_image(self.rebinned_image.image + noise_image, self)


    def calc_r_petro(self, r_petro_kpc=None):		# rename to "set_r_petro"
	if r_petro_kpc==None:
            i=0
	
	    image_to_use 	= self.noisy_image.image_in_nmaggies
	    RadiusObject 	= RadialInfo(self.noisy_image.n_pixels)
            PetroRatio 		= np.ones_like(RadiusObject.RadiusGrid)
            sumI_r 		= np.zeros_like(RadiusObject.RadiusGrid)

            for radius in RadiusObject.RadiusGrid:
                pflux_annulus 	= image_to_use[ RadiusObject.annulus_indices[i]]
                pflux_interior 	= image_to_use[RadiusObject.interior_indices[i]]
                sumI_r[i] 	= (np.sum(pflux_interior))
                if RadiusObject.annulus_sums[i]*RadiusObject.interior_sums[i] != 0.0:
                    PetroRatio[i] = (np.sum(pflux_annulus)/RadiusObject.annulus_sums[i])/(np.sum(pflux_interior)/RadiusObject.interior_sums[i])
                i=i+1

            Pind = np.argmin( np.absolute( np.flipud(PetroRatio) - 0.2) )
            PetroRadius = np.flipud(RadiusObject.RadiusGrid)[Pind]
	    r_petro_kpc = PetroRadius * self.noisy_image.pixel_in_kpc

	r_petro_pixels = r_petro_kpc / self.noisy_image.pixel_in_kpc	

	self.r_petro_pixels = r_petro_pixels
	self.r_petro_kpc    = r_petro_kpc


    def resize_image_from_rp(self):
	""" author: Greg Snyder """
	rp_pixel_in_kpc = 0.016 * self.r_petro_kpc			# P. Torrey -- this is my target scale; was 0.008, upping to 0.016 for GZ based on feedback
	Ntotal_new = (self.noisy_image.pixel_in_kpc / rp_pixel_in_kpc ) * self.noisy_image.n_pixels
        rebinned_image = congrid.congrid(self.noisy_image.image_in_nmaggies,  (Ntotal_new, Ntotal_new) )
	flux_consv_fac = np.sum(rebinned_image)/np.sum(self.noisy_image.image_in_nmaggies)
	rebinned_image /= flux_consv_fac

	diff = n_pixels_galaxy_zoo - Ntotal_new		#

        if diff >= 0:							# P. Torrey.  --  desired FOV is larger than already rendered... this is not a problem is image edges have ~0 flux.  Otherwise, can cause artifacts.
            shift = 0
            shiftc = np.floor(1.0*diff/2.0)
	    fake_image = np.zeros( (n_pixels_galaxy_zoo, n_pixels_galaxy_zoo) )
            fake_image[shiftc:shiftc+Ntotal_new,shiftc:shiftc+Ntotal_new] = rebinned_image[0:Ntotal_new, 0:Ntotal_new]
            rp_image = fake_image

	    rp_image = congrid.congrid(self.noisy_image.image_in_nmaggies,  (n_pixels_galaxy_zoo, n_pixels_galaxy_zoo) )
        else:
            shift = np.floor(-1.0*diff/2.0)
            rp_image = rebinned_image[shift:shift+n_pixels_galaxy_zoo,shift:shift+n_pixels_galaxy_zoo]

	self.rp_image.init_image(rp_image, self, fov = 424.0*(0.008 * self.r_petro_kpc) )

	
    def add_background(self, seed=1, include_background=True):
	""" author: Greg Snyder """
	bg_filename = (backgrounds[self.band])[0]
        file = pyfits.open(bg_filename) ; header = file[0].header ; pixsize = get_pixelsize_arcsec(header) ; Nx = header.get('NAXIS2') ; Ny = header.get('NAXIS1')
	
        Npix_get = np.floor(self.rp_image.n_pixels * self.rp_image.pixel_in_arcsec / pixsize)
	if (Npix_get > n_pixels_galaxy_zoo):				# P. Torrey 9/10/14   -- this is sub optimal, but necessary to avoid strange noise ...
	    Npix_get = n_pixels_galaxy_zoo				#			... in the images.  Could cause problems for automated analysis.

    	im = file[0].data 

        halfval_i = np.floor(np.float(Nx)/1.3)
        halfval_j = np.floor(np.float(Ny)/1.3)

	np.random.seed(seed=seed)

        starti = np.random.random_integers(5,halfval_i)
        startj = np.random.random_integers(5,halfval_j)

        nanomaggies = im[starti:starti+Npix_get,startj:startj+Npix_get]
        nanomaggies_gridded = congrid.congrid(nanomaggies, (n_pixels_galaxy_zoo, n_pixels_galaxy_zoo))
        factor = np.sum(nanomaggies_gridded)/np.sum(nanomaggies)
	bg_image = nanomaggies_gridded / factor

	if include_background:
	   self.bg_image.init_image(bg_image + self.rp_image.image, self, fov = self.rp_image.pixel_in_kpc * self.rp_image.n_pixels)
	else:
	   self.bg_image.init_image(self.rp_image.image, self, fov = self.rp_image.pixel_in_kpc * self.rp_image.n_pixels)


    def save_bgimage_fits(self,outputfitsfile):
	""" Written by G. Snyder 8/4/2014 to output FITS files from Sunpy module """
        theobj = self.bg_image
        #create primary HDU (the "final" image) and save important header information -- may want to verify that I got these right
        #Are there other quantities of interest??
        primhdu = pyfits.PrimaryHDU(theobj.image) ; primhdu.header.update('IMUNIT','NMAGGIE',comment='approx 3.63e-6 Jy')
        primhdu.header.update('ABABSZP',22.5,'For Final Image')  #THIS SHOULD BE CORRECT FOR NANOMAGGIE IMAGES ONLY
        primhdu.header.update('ORIGZP',theobj.ab_abs_zeropoint,'For Original Image')
        primhdu.header.update('PIXSCALE',theobj.pixel_in_arcsec,'For Final Image, arcsec')
        primhdu.header.update('PIXORIG', theobj.camera_pixel_in_arcsec, 'For Original Image, arcsec')
        primhdu.header.update('PIXKPC',theobj.pixel_in_kpc, 'KPC')
        primhdu.header.update('ORIGKPC',self.sunrise_image.pixel_in_kpc,'For Original Image, KPC')
        primhdu.header.update('NPIX',theobj.n_pixels)
        primhdu.header.update('NPIXORIG',self.sunrise_image.n_pixels)

        primhdu.header.update('REDSHIFT',self.cosmology.redshift)
        primhdu.header.update('LUMDIST' ,self.cosmology.lum_dist, 'MPC')
        primhdu.header.update('ANGDIST' ,self.cosmology.ang_diam_dist, 'MPC')
        primhdu.header.update('PSCALE'  ,self.cosmology.kpc_per_arcsec,'KPC')

        primhdu.header.update('H0',self.cosmology.H0)
        primhdu.header.update('WM',self.cosmology.WM)
        primhdu.header.update('WV',self.cosmology.WV)

        primhdu.header.update('PSFFWHM',self.telescope.psf_fwhm_arcsec,'arcsec')
        primhdu.header.update('TPIX',self.telescope.pixelsize_arcsec,'arcsec')

        primhdu.header.update('FILTER', self.band_name)
        primhdu.header.update('FILE',self.filename)
        primhdu.update_ext_name('SYNTHETIC_IMAGE')

        #Optionally, we can save additional images alongside these final ones
        #e.g., the raw sunrise image below
        #simhdu = pyfits.ImageHDU(self.sunriseimage, header=self.image_header) ; zhdu.update_ext_name('SIMULATED_IMAGE')
        #newlist = pyfits.HDUList([primhdu, simhdu])

        #create HDU List container
        newlist = pyfits.HDUList([primhdu])

        #save container to file, overwriting as needed
        newlist.writeto(outputfitsfile,clobber=True)




#    return b_nanomaggies_gridded/b_factor, g_nanomaggies_gridded/g_factor, r_nanomaggies_gridded/r_factor


def get_pixelsize_arcsec(header):
    cd1_1 = header.get('CD1_1')  # come in degrees
    cd1_2 = header.get('CD1_2')

    pix_arcsec = 3600.0*(cd1_1**2 + cd1_2**2)**0.5

    return pix_arcsec



class RadialInfo:
    """ Class for giving radial profile info for rp calcultions """
    def __init__(self,N):
        self.RadiusGrid = np.linspace(0.0001,1.5*N,num=40)
        self.Npix = N
        self.annulus_indices = []
        self.interior_indices = []
        self.annulus_sums = []
        self.interior_sums = []

        self.xgrid = np.linspace(float(-self.Npix)/2.0 + 0.5,float(self.Npix)/2.0 - 0.5,num=self.Npix)

        self.xsquare = np.zeros((self.Npix,self.Npix))
        self.ysquare = np.zeros_like(self.xsquare)

        ones = np.ones((self.Npix,self.Npix))

        for j in range(self.Npix):
            self.xsquare[j,:] = self.xgrid
            self.ysquare[:,j] = self.xgrid

        i=0
        for i,rad in enumerate(self.RadiusGrid):
            self.annulus_indices.append(np.where(np.logical_and( (self.xsquare**2 + self.ysquare**2)**0.5 < 1.25*rad, (self.xsquare**2 + self.ysquare**2)**0.5 > 0.8*rad )) )
            self.interior_indices.append(np.where((self.xsquare**2 + self.ysquare**2)**0.5 < rad) )
            self.annulus_sums.append( np.sum(ones[self.annulus_indices[i]]) )
            self.interior_sums.append( np.sum(ones[self.interior_indices[i]]) )



class fits_header:
  def __init__(self, filename):
    if (not os.path.exists(filename)):
      print "file not found:", filename
      sys.exit()

    hdulist = fits.open(filename)
    self.info = hdulist.info()



def my_fits_open(filename):
    if (not os.path.exists(filename)):
        print "file not found:", filename
        sys.exit()

    return fits.open(filename)















