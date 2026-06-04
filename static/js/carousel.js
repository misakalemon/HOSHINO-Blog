if ($(".sw-layout").length > 0) {
    $(".sw-layout").each(function () {
        var tfSwCategories = $(this);
        var preview = tfSwCategories.data("preview");
        var tablet = tfSwCategories.data("tablet");
        var mobile = tfSwCategories.data("mobile");
        var screenXl = tfSwCategories.data("screen-xl") || preview;
        var mobileSm =
            tfSwCategories.data("mobile-sm") !== undefined
                ? tfSwCategories.data("mobile-sm")
                : mobile;
        var spacingLg = tfSwCategories.data("space-lg");
        var spacingMd = tfSwCategories.data("space-md");
        var spacing = tfSwCategories.data("space");
        var perGroup = tfSwCategories.data("pagination") || 1;
        var perGroupMd = tfSwCategories.data("pagination-md") || 1;
        var perGroupLg = tfSwCategories.data("pagination-lg") || 1;
        var loop = tfSwCategories.data("loop") || false;
        var center = tfSwCategories.data("slide-center") || false;
        var intitSlide = tfSwCategories.data("init-slide") || 0;
        var mouseScroll = tfSwCategories.data("mouse-scroll") || false;
        var swiperInstance;
        function initSwiper() {
            if (swiperInstance) swiperInstance.destroy(true, true);
            swiperInstance = new Swiper(tfSwCategories[0], {
                slidesPerView: mobile,
                spaceBetween: spacing,
                speed: 1000,
                centeredSlides: center,
                initialSlide: intitSlide,
                pagination: {
                    el: tfSwCategories.find(".sw-pagination-layout")[0],
                    clickable: true,
                },
                slidesPerGroup: perGroup,
                observer: true,
                observeParents: true,
                navigation: {
                    clickable: true,
                    nextEl: tfSwCategories.find(".nav-next-layout")[0],
                    prevEl: tfSwCategories.find(".nav-prev-layout")[0],
                },
                loop: loop,
                breakpoints: {
                    575: {
                        slidesPerView: mobileSm,
                        spaceBetween: spacing,
                        slidesPerGroup: perGroup,
                    },
                    768: {
                        slidesPerView: tablet,
                        spaceBetween: spacingMd,
                        slidesPerGroup: perGroupMd,
                    },
                    992: {
                        slidesPerView: preview,
                        spaceBetween: spacingLg,
                        slidesPerGroup: perGroupLg,
                    },
                    1200: {
                        slidesPerView: screenXl,
                        spaceBetween: spacingLg,
                        slidesPerGroup: perGroupLg,
                    },
                },
            });

            if (mouseScroll) {
                tfSwCategories[0].addEventListener(
                    "wheel",
                    function (e) {
                        e.preventDefault();
                        if (e.deltaY > 0) {
                            swiperInstance.slideNext();
                        } else {
                            swiperInstance.slidePrev();
                        }
                    },
                    { passive: false }
                );
            }
        }

        initSwiper();
        window.addEventListener("resize", function () {
            initSwiper();
        });
    });
}

if ($(".sw-layout-1").length > 0) {
    $(".sw-layout-1").each(function () {
        var tfSwCategories = $(this);
        var swiperContainer = tfSwCategories.find(".swiper");
        var preview = swiperContainer.data("preview") || 1;
        var tablet = swiperContainer.data("tablet") || 1;
        var mobile = swiperContainer.data("mobile") || 1;
        var mobileSm = swiperContainer.data("mobile-sm") || mobile;
        var spacingLg = swiperContainer.data("space-lg") || 10;
        var spacingMd = swiperContainer.data("space-md") || 10;
        var spacing = swiperContainer.data("space") || 10;
        var perGroup = swiperContainer.data("pagination") || 1;
        var perGroupMd = swiperContainer.data("pagination-md") || 1;
        var perGroupLg = swiperContainer.data("pagination-lg") || 1;
        var grid = swiperContainer.data("grid") || 1;
        var mdGrid = swiperContainer.data("mdgrid") || 1;
        var lgGrid = swiperContainer.data("lggrid") || 1;
        var paginationType =
            swiperContainer.data("pagination-type") || "bullets";
        var loop =
            swiperContainer.data("loop") !== undefined
                ? swiperContainer.data("loop")
                : false;
        var mouseScroll = swiperContainer.data("mouse-scroll") || false;
        var nextBtn = tfSwCategories.find(".nav-next-layout-1")[0] || null;
        var prevBtn = tfSwCategories.find(".nav-prev-layout-1")[0] || null;
        var progressbar =
            swiperContainer.find(".sw-fraction-layout-1")[0] ||
            tfSwCategories.find(".sw-fraction-layout-1")[0] ||
            tfSwCategories.find(".sw-progress-layout-1")[0] ||
            null;
        var swiper = new Swiper(swiperContainer[0], {
            slidesPerView: mobile,
            spaceBetween: spacing,
            speed: 1000,
            pagination: {
                el: progressbar,
                clickable: true,
                type: paginationType,
            },
            grid: {
                rows: grid,
                fill: "row",
            },
            observer: true,
            observeParents: true,
            navigation: {
                clickable: true,
                nextEl: nextBtn,
                prevEl: prevBtn,
            },
            loop: loop,
            breakpoints: {
                575: {
                    slidesPerView: mobileSm,
                    spaceBetween: spacing,
                    slidesPerGroup: perGroup,
                },
                768: {
                    slidesPerView: tablet,
                    spaceBetween: spacingMd,
                    slidesPerGroup: perGroupMd,
                    grid: {
                        rows: mdGrid,
                        fill: "row",
                    },
                },
                1200: {
                    slidesPerView: preview,
                    spaceBetween: spacingLg,
                    slidesPerGroup: perGroupLg,
                    grid: {
                        rows: lgGrid,
                        fill: "row",
                        gap: 12,
                    },
                },
            },
        });

        if (mouseScroll) {
            tfSwCategories[0].addEventListener(
                "wheel",
                function (e) {
                    e.preventDefault();
                    if (e.deltaY > 0) {
                        swiper.slideNext();
                    } else {
                        swiper.slidePrev();
                    }
                },
                { passive: false }
            );
        }
    });
}

if ($(".sw-single").length > 0) {
    $(".sw-single").each(function (index) {
        var tfSwCategories = $(this);
        var effect = tfSwCategories.data("effect");
        var loop = tfSwCategories.data("loop") || false;

        function setParallaxAttributes(element, duration) {
            element.setAttribute("data-swiper-parallax-x", "-400");
            element.setAttribute("data-swiper-parallax-duration", duration);
        }

        var postContentContainer = ".cs-entry__content";
        var sliders = document.querySelectorAll(".animation-sl");

        sliders.forEach(function (slider) {
            var parallaxValue = slider.getAttribute("data-cs-parallax");
            var parallax = !!parallaxValue ? true : false;
            if (parallax) {
                var postContents =
                    tfSwCategories[0].querySelectorAll(postContentContainer);
                if (postContents.length > 0) {
                    postContents.forEach(function (postContent) {
                        setParallaxAttributes(postContent, "800");
                    });
                }
            }
        });

        var postContents =
            tfSwCategories[0].querySelectorAll(postContentContainer);

        var swiperSlider = {
            slidesPerView: 1,
            speed: 1000,
            loop: loop,
            parallax: true,
            navigation: {
                clickable: true,
                nextEl: `.sw-single-next-${index}`,
                prevEl: `.sw-single-prev-${index}`,
            },
            pagination: {
                el: `.sw-pagination-single-${index}`,
                clickable: true,
            },
            on: {
                init: function init() {
                    var _this = this;
                    setTimeout(function () {
                        var initialSlide = _this.slides[_this.activeIndex];
                        if (initialSlide) {
                            var initialContent =
                                initialSlide.querySelector(
                                    postContentContainer
                                );
                            if (initialContent) {
                                initialContent.style.transform = "none";
                            }
                        }
                    }, 100);
                },
                slideChange: function slideChange() {
                    var currentSlide = this.slides[this.activeIndex];
                    postContents.forEach(function (postContent) {
                        if (
                            postContent ===
                            currentSlide.querySelector(postContentContainer)
                        ) {
                            postContent.style.transform = "none";
                        }
                    });
                },
            },
        };

        if (effect === "fade") {
            swiperSlider.effect = "fade";
            swiperSlider.fadeEffect = {
                crossFade: true,
            };
        }
        if (effect === "creative") {
            swiperSlider.effect = "creative";
            swiperSlider.creativeEffect = {
                prev: {
                    shadow: true,
                    translate: [0, 0, -400],
                },
                next: {
                    translate: ["100%", 0, 0],
                },
            };
        }

        tfSwCategories
            .find(".sw-single-next")
            .addClass(`sw-single-next-${index}`);
        tfSwCategories
            .find(".sw-single-prev")
            .addClass(`sw-single-prev-${index}`);
        tfSwCategories
            .find(".sw-pagination-single")
            .addClass(`sw-pagination-single-${index}`);

        new Swiper(tfSwCategories[0], swiperSlider);
    });
}

if ($(".thumbs-sw-pagi").length > 0) {
    var preview = $(".thumbs-sw-pagi").data("preview");
    var spacing = $(".thumbs-sw-pagi").data("space");
    var mobile = $(".thumbs-sw-pagi").data("mobile");
    var mobileSm = $(".thumbs-sw-pagi").data("mobile-sm");

    var pagithumbs = new Swiper(".thumbs-sw-pagi", {
        spaceBetween: spacing,
        slidesPerView: "auto",
        freeMode: true,
        watchSlidesProgress: true,
        navigation: {
            clickable: true,
            nextEl: ".sw-pagi-next",
            prevEl: ".sw-pagi-prev",
        },
        breakpoints: {
            375: {
                slidesPerView: 3,
                spaceBetween: spacing,
            },
            500: {
                slidesPerView: mobileSm,
            },
        },
    });
}

if ($(".sw-single-1").length > 0) {
    var loop = $(".sw-single-1").data("loop") || false;
    var swiperSingle = new Swiper(".sw-single-1", {
        spaceBetween: 16,
        autoplay: {
            delay: 5000,
            disableOnInteraction: false,
        },
        speed: 1000,
        effect: "fade",
        fadeEffect: {
            crossFade: true,
        },
        thumbs: {
            swiper: pagithumbs,
        },
        navigation: {
            clickable: true,
            nextEl: ".sw-thumbs-next",
            prevEl: ".sw-thumbs-prev",
        },
    });
}
