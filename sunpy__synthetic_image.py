#!/usr/bin/env python
""" Defines the synthetic_image class to add image realism to the idealized sunrise images.

The synthetic_image class defines a number of routines to take the original image and 
convolve it with some psf function, add sky noise, rebin to an appropate pixel scale 
(based on telescope), scale to an approparte image size (based on a petrosian radius 
calculation, and add background image (SDSS only supported at the moment).


The majority of the code in this file was developed by Greg Snyder and can be found in
	 Snyder et al., (XXXX) XXXX, XXXX


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
import scipy.interpolate

import sunpy.sunpy__load
import time
import cosmocalc

import wget

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

verbose=True


abs_dist        = 0.01         
erg_per_joule   = 1e7
speedoflight_m  = 2.99e8
m2_to_cm2       = 1.0e-4
n_arcsec_per_str = 4.255e10             # (radian per arc second)^2
n_pixels_galaxy_zoo = 424 


###########################################################
# SDSS background images created by Greg Snyder on 6/18/14#
# SDSS background obtained from:  data.sdss3.org/mosaics  #
# Ra = 175.0
# Dec = 30.0
# Size (deg) = 0.5
# Pixel Scale = 0.24 "/pixel
#
# HST backgrounds provided by Erica Nelson and Pascal Oesch 
# and integrated here by P. Torrey
# #########################################################

dl_base="http://illustris.rc.fas.harvard.edu/data/illustris_images_aux/backgrounds"
bg_base='/n/home01/ptorrey/Python/OwnModules/sunpy/backgrounds'
bg_base='./data/'
backgrounds = [	[], [], 		# GALEX 0 1
		[bg_base+'/SDSS_backgrounds/J113959.99+300000.0-u.fits'], 	# 2 SDSS-u 
		[bg_base+'/SDSS_backgrounds/J113959.99+300000.0-g.fits'], 	# 3 SDSS-g
		[bg_base+'/SDSS_backgrounds/J113959.99+300000.0-r.fits'], 	# 4 SDSS-r
		[bg_base+'/SDSS_backgrounds/J113959.99+300000.0-i.fits'], 	# 5 SDSS-i
		[bg_base+'/SDSS_backgrounds/J113959.99+300000.0-z.fits'], 	# 6 SDSS-z
		[], [], [], [],				# 7-8-9-10 IRAC
		[], [], [], [], [], [], [], [], [], [], 	# 11-12-13-14-15-16-17-18 JOHNSON/COUSINS + 2 mass
		[bg_base+'/HST_backgrounds/xdf_noise_F775W_30mas.fits'], #21	ACS-435
		[bg_base+'/HST_backgrounds/GOODSN_F606W.fits'], #22	ACS-606
		[bg_base+'/HST_backgrounds/xdf_noise_F775W_30mas.fits'], #23 	ACS-775
		[bg_base+'/HST_backgrounds/xdf_noise_F775W_30mas.fits'], #24	ACS-850
		[bg_base+'/HST_backgrounds/GOODSN_F125W.fits'],		 #25	f105w
	        [bg_base+'/HST_backgrounds/GOODSN_F125W.fits'],		 #26    f125w
		[bg_base+'/HST_backgrounds/GOODSN_F160W.fits'],		 #27	f160w
		[], [], [], [], [], [], [], []		# NIRCAM
		]

bg_zpt = [ [], [],                 # GALEX
                        [22.5],
                        [22.5],
                        [22.5],
                        [22.5],
                        [22.5],
                [], [], [], [],                         # 7-8-9-10 IRAC
                [], [], [], [], [], [], [], [], [], [],         # 11-12-13-14-15-16-17-18 JOHNSON/COUSINS + 2 mass
                [25.69],
                [25.69],
                [25.69],
                [25.69],
                [25.69],
                [25.69],
                [25.69],
                [], [], [], [], [], [], [], []          # NIRCAM
                ]


def build_synthetic_image(filename, band, r_petro_kpc=None, **kwargs):
    """ build a synthetic image from a SUNRISE fits file and return the image to the user """
    obj     	 = synthetic_image(filename, band=band, r_petro_kpc=r_petro_kpc, **kwargs)
    return obj.bg_image.return_image(), obj.r_petro_kpc, obj.seed, obj.bg_failed

def load_resolved_broadband_apparent_magnitudes(filename, redshift, camera=0, seed=12345, n_bands=36, **kwargs):
    """ loads n_band x n_pix x n_pix image array with apparent mags for synthetic images """
    mags   = sunpy.sunpy__load.load_all_broadband_photometry(filename, camera=0)

    for band in np.arange(n_bands):
        obj          = synthetic_image(filename, band=int(band), seed=seed, redshift=redshift, **kwargs)    
	img = obj.bg_image.return_image()		#  muJy / str
	if band==0:
	    n_pixels = img.shape[0]
	    all_images = np.zeros( (n_bands, n_pixels, n_pixels ) )
	all_images[band, :, :] = img			# muJy / str

        pixel_in_sr = (1e3*obj.bg_image.pixel_in_kpc /10.0)**2

    
    all_images *=  pixel_in_sr / 1e6    	# in Jy

    for band in np.arange(n_bands):
        tot_img_in_Jy = np.sum(all_images[band,:,:])    # total image flux in Jy
        abmag = -2.5 * np.log10(tot_img_in_Jy / 3631 )
        if verbose:
            print "the ab magnitude of band "+str(band)+" is :"+str(abmag)+"  "+str(mags[band])
            print abmag/mags[band], abmag - mags[band]
	    print " "

    all_images = -2.5 * np.log10( all_images / 3631 )                   # abmag in each pixel
    dist = (cosmocalc.cosmocalc(redshift, H0=70.4, WM=0.2726, WV=0.7274))['DL_Mpc'] * 1e6
    dist_modulus = 5.0 * ( np.log10(dist) - 1.0 )
    apparent_magnitudes = dist_modulus + all_images
    return apparent_magnitudes


class synthetic_image:
    """ main class for loading and manipulating SUNRISE data into real data format  """
    def __init__(self, 
			filename, band=0, camera=0, 
			redshift=0.05, 
			psf_fwhm_arcsec=1.0, pixelsize_arcsec=0.24, 
			r_petro_kpc=None, save_fits=False, 
			seed=None, 
			add_background=True,
			add_psf=True,
			add_noise=True,
			rebin_phys=True,
			rebin_gz=False,
			n_target_pixels=n_pixels_galaxy_zoo,
			resize_rp=True,
			sn_limit=25.0,
			sky_sig=None,
			verbose=True,
			fix_seed=True,
			**kwargs):

        if (not os.path.exists(filename)):
            print "file not found:", filename
            sys.exit()

	start_time = time.time()
	self.filename  = filename
	self.cosmology = cosmology(redshift)
	self.telescope = telescope(psf_fwhm_arcsec, pixelsize_arcsec)

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

        to_nu                     = ((self.lambda_eff**2 ) / (speedoflight_m)) #* pixel_area_in_str
        to_microjanskies          = (1.0e6) * to_nu * (1.0e26)                 # 1 muJy/str (1Jy = 1e-26 W/m^2/Hz)

	this_image = all_images[band,:,:]
	this_image = this_image * to_microjanskies 		# to microjanskies / str

	if verbose:
	    print "SUNRISE calculated the abmag for this system to be:"
	    print self.filter_data.AB_mag_nonscatter0[band]

	self.sunrise_image.init_image(this_image, self, comoving_to_phys_fov=False)
	# assume now that all images are in micro-Janskies per str

	self.add_gaussian_psf(add_psf=add_psf)
	self.rebin_to_physical_scale(rebin_phys=rebin_phys)
	self.add_noise(add_noise=add_noise, sn_limit=sn_limit, sky_sig=sky_sig)
	self.calc_r_petro(r_petro_kpc=r_petro_kpc, resize_rp=resize_rp)
	self.resize_image_from_rp(resize_rp=resize_rp)

	self.seed = seed
        self.bg_failed= False
	self.seed = self.add_background(seed=self.seed, add_background=add_background, rebin_gz=rebin_gz, n_target_pixels=n_target_pixels, fix_seed=fix_seed)

	end_time   = time.time()
        if verbose:
	    print " "
	    print " "
	    print "init images + adding realism took "+str(end_time - start_time)+" seconds"
 	    print "preparing to save "+filename[:filename.index('broadband')]+'synthetic_image_'+filename[filename.index('broadband_')+10:filename.index('.fits')]+'_band_'+str(self.band)+'_camera_'+str(camera)+'_'+str(int(self.seed))+'.fits'

	if save_fits:
	    orig_dir=filename[:filename.index('broadband')]
	    outputfitsfile = orig_dir+'synthetic_image_'+filename[filename.index('broadband_')+10:filename.index('.fits')]+'_band_'+str(self.band)+'_camera_'+str(camera)+'_'+str(int(self.seed))+'.fits'
	    self.save_bgimage_fits(outputfitsfile)


    def add_gaussian_psf(self, add_psf=True, sample_factor=1.0):		# operates on sunrise_image -> creates psf_image
	if add_psf:
	    current_psf_sigma_pixels = self.telescope.psf_fwhm_arcsec * (1.0/2.355) / self.sunrise_image.pixel_in_arcsec

	    if current_psf_sigma_pixels<8:	# want the psf sigma to be resolved with (at least) 8 pixels...
	        target_psf_sigma_pixels  = 8.0
	        n_pixel_new = np.floor(self.sunrise_image.n_pixels * target_psf_sigma_pixels / current_psf_sigma_pixels )

	        if n_pixel_new > 2500:		# an upper limit owing to memory constraints...  
						# beyond this, the PSF is already very small...
		    n_pixel_new = 2500
		    target_psf_sigma_pixels = n_pixel_new * current_psf_sigma_pixels / self.sunrise_image.n_pixels

	        new_image = congrid(self.sunrise_image.image,  (n_pixel_new, n_pixel_new) )
	        current_psf_sigma_pixels = target_psf_sigma_pixels * (
			(self.sunrise_image.n_pixels * target_psf_sigma_pixels 
				/ current_psf_sigma_pixels) / n_pixel_new )
	    else:
	        new_image = self.sunrise_image.image

	    psf_image = np.zeros_like( new_image ) * 1.0
	    dummy = sp.ndimage.filters.gaussian_filter(new_image, 
			current_psf_sigma_pixels, output=psf_image, mode='constant')

	    self.psf_image.init_image(psf_image, self) 
	else:
	    self.psf_image.init_image(self.sunrise_image.image, self)


    def rebin_to_physical_scale(self, rebin_phys=True):
	if rebin_phys:
	    n_pixel_new = np.floor( ( self.psf_image.pixel_in_arcsec / self.telescope.pixelsize_arcsec )  * self.psf_image.n_pixels )
	    rebinned_image = congrid(self.psf_image.image,  (n_pixel_new, n_pixel_new) )
  	    self.rebinned_image.init_image(rebinned_image, self) 
	else:
	    self.rebinned_image.init_image(self.psf_image.image, self)

    def add_noise(self, add_noise=True, sky_sig=None, sn_limit=25.0):
	if add_noise:
	    if sky_sig==None:
	        total_flux 	= np.sum( self.rebinned_image.image )
	        area 		= 1.0 * self.rebinned_image.n_pixels * self.rebinned_image.n_pixels
	        sky_sig 	= np.sqrt( (total_flux / sn_limit)**2 / (area**2 ) )

	    noise_image 	=  sky_sig * np.random.randn( self.rebinned_image.n_pixels, self.rebinned_image.n_pixels ) 
	    new_image = self.rebinned_image.image + noise_image
	    self.noisy_image.init_image(new_image, self)
	else:
	    self.noisy_image.init_image(self.rebinned_image.image, self)


    def calc_r_petro(self, r_petro_kpc=None, resize_rp=True):		# rename to "set_r_petro"
        if ( resize_rp==False):
	    r_petro_kpc = 1.0;
	elif ( r_petro_kpc==None ):
            i=0
	
	    image_to_use 	= self.noisy_image.image		#_in_nmaggies
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
	else:
	    r_petro_kpc = r_petro_kpc


	r_petro_pixels = r_petro_kpc / self.noisy_image.pixel_in_kpc	

	self.r_petro_pixels = r_petro_pixels
	self.r_petro_kpc    = r_petro_kpc


    def resize_image_from_rp(self, resize_rp=True):
	if resize_rp:
	    rp_pixel_in_kpc = 0.008 * self.r_petro_kpc	# The target scale; was 0.008, upping to 0.016 for GZ based on feedback
	    Ntotal_new = int( (self.noisy_image.pixel_in_kpc / rp_pixel_in_kpc ) * self.noisy_image.n_pixels )
	    rebinned_image = congrid(self.noisy_image.image            ,  (Ntotal_new, Ntotal_new) )

	    diff = n_pixels_galaxy_zoo - Ntotal_new		#
            if diff >= 0:
                shift = int(np.floor(1.0*diff/2.0))
		lp = shift
		up = shift + Ntotal_new
	        tmp_image = np.zeros( (n_pixels_galaxy_zoo, n_pixels_galaxy_zoo) )
                tmp_image[lp:up,lp:up] = rebinned_image[0:Ntotal_new, 0:Ntotal_new]
                rp_image = tmp_image
            else:
                shift = int( np.floor(-1.0*diff/2.0) )
                lp = int(shift)
		up = int(shift+n_pixels_galaxy_zoo)
                rp_image = rebinned_image[lp:up, lp:up]	

	    self.rp_image.init_image(rp_image, self, fov = 424.0*(0.008 * self.r_petro_kpc) )
	else:
	    self.rp_image.init_image(self.noisy_image.image, self, fov=self.noisy_image.pixel_in_kpc*self.noisy_image.n_pixels)

	
    def add_background(self, seed=1, add_background=True, rebin_gz=False, n_target_pixels=424, fix_seed=True):
	if add_background and (len(backgrounds[self.band]) > 0):
		bg_image = 10.0*self.rp_image.image		# dummy values for while loop condition

		tot_bg = np.sum(bg_image)
                tot_img= np.sum(self.rp_image.image)
		tol_fac = 1.0

		while(tot_bg > tol_fac*tot_img):	

	    #=== load *full* bg image, and its properties ===#  
	            bg_filename = (backgrounds[self.band])[0]
		    if not (os.path.isfile(bg_filename)):
		        print "  Background files were not found...  "
                        print "  The standard files used in Torrey al. (2015), Snyder et al., (2015) and Genel et al., (2014) ..."
			print "  can be downloaded using the download_backgrounds routine or manually from:  "
			print "     http://illustris.rc.fas.harvard.edu/data/illustris_images_aux/backgrounds/SDSS_backgrounds/J113959.99+300000.0-u.fits "
			print "     http://illustris.rc.fas.harvard.edu/data/illustris_images_aux/backgrounds/SDSS_backgrounds/J113959.99+300000.0-g.fits "
			print "     http://illustris.rc.fas.harvard.edu/data/illustris_images_aux/backgrounds/SDSS_backgrounds/J113959.99+300000.0-r.fits "
			print "     http://illustris.rc.fas.harvard.edu/data/illustris_images_aux/backgrounds/SDSS_backgrounds/J113959.99+300000.0-i.fits "
			print "     http://illustris.rc.fas.harvard.edu/data/illustris_images_aux/backgrounds/SDSS_backgrounds/J113959.99+300000.0-z.fits "
			print "  "
			print "  Contact Paul Torrey (ptorrey@mit.edu) or Greg Snyder (gsnyder@stsci.edu) with further questions "
                    file = pyfits.open(bg_filename) ; 
                    header = file[0].header ; 
                    pixsize = get_pixelsize_arcsec(header) ; 
                    Nx = header.get('NAXIS2') ; Ny = header.get('NAXIS1')
	
	        #=== figure out how much of the image to extract ===#
                    Npix_get = np.floor(self.rp_image.n_pixels * self.rp_image.pixel_in_arcsec / pixsize)

	            if (Npix_get > self.rp_image.n_pixels):	# P. Torrey 9/10/14   -- sub optimal, but avoids strange noise ...
	                Npix_get = self.rp_image.n_pixels	#		... in the images.  Could cause problems for automated analysis.
  
    	            im = file[0].data 	# this is in some native units
                    halfval_i = np.floor(np.float(Nx)/1.3)
	            halfval_j = np.floor(np.float(Ny)/1.3)
		    print seed
	            np.random.seed(seed=int(seed))

                    starti = np.random.random_integers(5,halfval_i)
                    startj = np.random.random_integers(5,halfval_j)

                    bg_image_raw = im[starti:starti+Npix_get,startj:startj+Npix_get]

	            #=== need to convert to microJy / str ===#
	            bg_image_muJy = bg_image_raw * 10.0**(-0.4*(bg_zpt[self.band][0]- 23.9 ))
	            pixel_area_in_str       = pixsize**2 / n_arcsec_per_str
	            bg_image = bg_image_muJy / pixel_area_in_str 

	            #=== need to rebin bg_image  ===#
                    bg_image = congrid(bg_image, (self.rp_image.n_pixels, self.rp_image.n_pixels)) 

		    #=== compare sum(bg_image) to sum(self.rp_image.image) ===#
		    if (fix_seed):
			tot_bg = 0
		    else:
		        tot_bg = np.sum(bg_image)
		        tot_img= np.sum(self.rp_image.image)
		        #print tot_bg, tot_img, tot_bg/tot_img
		        #print np.max(bg_image), np.max(self.rp_image.image), np.max(bg_image)/ np.max(self.rp_image.image)
			if(tot_bg > tol_fac*tot_img):
			    seed+=1


		
	        new_image = bg_image + self.rp_image.image
	        new_image[ new_image < self.rp_image.image.min() ] = self.rp_image.image.min()
		if (new_image.mean() > (5*self.rp_image.image.mean()) ):
			self.bg_failed=True
		#else:
		        #print self.rp_image.image.min(), self.rp_image.image.max(), self.rp_image.image.mean()
		        #print new_image.min(), new_image.max(), new_image.mean()
	else:
	        new_image = self.rp_image.image

	if rebin_gz:
	    new_image = congrid( new_image, (n_target_pixels, n_target_pixels) )
	        
	self.bg_image.init_image(new_image, self, fov = self.rp_image.pixel_in_kpc * self.rp_image.n_pixels)	
	return seed



    def save_bgimage_fits(self,outputfitsfile, save_img_in_muJy=False):
	""" Written by G. Snyder 8/4/2014 to output FITS files from Sunpy module """
        theobj = self.bg_image

	myimage = theobj.return_image()		# in muJy / str 
        image = np.zeros( myimage.shape )
        image[:,:] = myimage[:,:]
	print "before converting and saving the image min/max are:"
        print image.min(), image.max(), np.sum(image)


	pixel_area_in_str = theobj.pixel_in_arcsec**2 / n_arcsec_per_str
	image *= pixel_area_in_str      # in muJy 
        if save_img_in_muJy == False:
	    if len(bg_zpt[self.band]) > 0:
                image = image / ( 10.0**(-0.4*(bg_zpt[self.band][0]- 23.9 )) ) 
	else:
	    ' '
	    'saving image in muJy!!!!!'
	    ' '

	print "before saving the image min/max are:"
	print image.min(), image.max(), np.sum(image) 

        primhdu = pyfits.PrimaryHDU(image) ; primhdu.header.update('IMUNIT','NMAGGIE',comment='approx 3.63e-6 Jy')
        primhdu.header.update('ABABSZP',22.5,'For Final Image')  #THIS SHOULD BE CORRECT FOR NANOMAGGIE IMAGES ONLY
#        primhdu.header.update('ORIGZP',theobj.ab_abs_zeropoint,'For Original Image')
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

    if cd1_2==None:
	cd1_2 = header.get('CD2_2')

    try:
        pix_arcsec = 3600.0*(cd1_1**2 + cd1_2**2)**0.5
    except:
	print "WARNING!!! SETTING PIXEL SCALE MANUALLY!"
	pix_arcsec = 0.05

    return pix_arcsec



class RadialInfo:
    """ Class for giving radial profile info for rp calcultions """
    def __init__(self,N):
        self.RadiusGrid = np.linspace(0.0001,1.5*N,num=400)
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

    def init_image(self, image, parent_obj, fov=None, comoving_to_phys_fov=False):
        self.image              = image
        self.n_pixels           = image.shape[0]
        if fov==None:
	    if comoving_to_phys_fov:
                self.pixel_in_kpc           = parent_obj.param_header.get('linear_fov') / self.n_pixels / (parent_obj.cosmology.redshift+1)
	    else:
		self.pixel_in_kpc           = parent_obj.param_header.get('linear_fov') / self.n_pixels
        else:
            self.pixel_in_kpc           = fov / self.n_pixels
        self.pixel_in_arcsec    = self.pixel_in_kpc / parent_obj.cosmology.kpc_per_arcsec
        self.image_exists       = True
        self.camera_pixel_in_arcsec = (self.pixel_in_kpc / parent_obj.param_header.get('cameradist') ) * 2.06e5

	pixel_in_sr = (1e3*self.pixel_in_kpc /10.0)**2
	image_in_muJy =  self.image  * pixel_in_sr		# should now have muJy
        tot_img_in_Jy = np.sum(image_in_muJy) / 1e6		# now have total image flux in Jy
	abmag = -2.5 * np.log10(tot_img_in_Jy / 3631 )
#	print "the ab magnitude of this image is :"+str(abmag)

#	print " "
#	print " "
#	print "The FoV is :"
#	print self.pixel_in_kpc * self.n_pixels 
#	print ""
#	print " "


    def calc_ab_abs_zero(self, parent_obj):
        lambda_eff_in_m         = parent_obj.lambda_eff
        pixel_area_in_str       = self.camera_pixel_in_arcsec**2 / n_arcsec_per_str
        cameradist_in_kpc       = parent_obj.param_header.get('cameradist')

        to_nu                     = ((lambda_eff_in_m**2 ) / (speedoflight_m))* pixel_area_in_str
        to_microjanskies          = (1.0e6) * to_nu * (1.0e26)             # 1 Jy = 1e-26 W/m^2/Hz
        to_microjanskies_at_10pc  = to_microjanskies * (cameradist_in_kpc / abs_dist)**2  

        ab_abs_zeropoint = 23.90 - (2.5*np.log10(to_microjanskies_at_10pc))             
        self.ab_abs_zeropoint = ab_abs_zeropoint

    def convert_orig_to_nanomaggies(self, parent_obj):
        distance_factor = (10.0 / (parent_obj.cosmology.lum_dist * 1.0e6))**2
        orig_to_nmaggies = distance_factor * 10.0**(0.4*(22.5 - self.ab_abs_zeropoint) )
        self.image_in_nmaggies = self.image * orig_to_nmaggies

    def return_image(self):
#	fixed_norm_fac		= 10.0 / n_arcsec_per_str	# should probably get rid of this
        return self.image #* fixed_norm_fac 


def return_img_nanomaggies_to_orig(image_nm, lum_dist, ab_abs_zeropoint):
    distance_factor = (10.0 / (lum_dist * 1.0e6))**2
    orig_to_nmaggies = distance_factor * 10.0**(0.4*(22.5 - ab_abs_zeropoint) )
    return image_nm / orig_to_nmaggies






def congrid(a, newdims, centre=False, minusone=False):
    ''' Slimmed down version of congrid as originally obtained from:
		http://wiki.scipy.org/Cookbook/Rebinning
    '''
    if not a.dtype in [np.float64, np.float32]:
        a = np.cast[float](a)

    m1 = np.cast[int](minusone)
    ofs = np.cast[int](centre) * 0.5
    old = np.array( a.shape )
    ndims = len( a.shape )
    if len( newdims ) != ndims:
        print "[congrid] dimensions error. " \
              "This routine currently only support " \
              "rebinning to the same number of dimensions."
        return None
    newdims = np.asarray( newdims, dtype=float )
    dimlist = []



    for i in range( ndims ):
        base = np.arange( newdims[i] )
        dimlist.append( (old[i] - m1) / (newdims[i] - m1) \
                            * (base + ofs) - ofs )
    # specify old dims
    olddims = [np.arange(i, dtype = np.float) for i in list( a.shape )]

    # first interpolation - for ndims = any
    mint = scipy.interpolate.interp1d( olddims[-1], a, kind='linear', bounds_error=False, fill_value=0.0 )
    newa = mint( dimlist[-1] )

    trorder = [ndims - 1] + range( ndims - 1 )
    for i in range( ndims - 2, -1, -1 ):
        newa = newa.transpose( trorder )

        mint = scipy.interpolate.interp1d( olddims[i], newa, kind='linear', bounds_error=False, fill_value=0.0 )
        newa = mint( dimlist[i] )

    if ndims > 1:
        # need one more transpose to return to original dimensions
        newa = newa.transpose( trorder )

    return newa

def download_backgrounds():
    if not os.path.exists('./data'):
        os.makedirs('./data')
    if not os.path.exists('./data/SDSS_backgrounds'):
        os.makedirs('./data/SDSS_backgrounds')
    if not os.path.exists('./data/HST_backgrounds'):
        os.makedirs('./data/HST_backgrounds')
    for this_background in backgrounds:
        if len(this_background) > 0:
            if not (os.path.isfile(this_background[0])):
                url=dl_base+this_background[0][len(bg_base):]
                this_file = wget.download(url)
                os.rename(this_file, this_background[0])

                print url
