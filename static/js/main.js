/**

 * handleFooter
 * loadItem
 * changeValue
 * actionMusic
 * handleSidebar
 * oneNavOnePage
 * headerFixed
 * handlePopupSearch
 * video
 * goTop
 * wowAnimation
 * scrollTabsX
 * spliting
 ¸ü¶àÏÂÔØ£ºhttps://www.bootstrapmb.com 
**/

(function ($) {
    "use strict";

    const isMobile = () =>
        window.matchMedia("only screen and (max-width: 767px)").matches;

    /* headerFixed
  -------------------------------------------------------------------------------------*/
    const headerFixed = () => {
        const $header = $(".header-fixed");
        if (!$header.length) return;
        $(window).on("scroll", () => {
            $header.toggleClass("is-fixed", $(window).scrollTop() >= 350);
        });
    };

    /* handleFooter
  -------------------------------------------------------------------------------------*/
    const handleFooter = () => {
        const $headers = $(".footer-heading-mobile");
        const initAccordion = () => {
            if (isMobile() && !$headers.data("accordion-initialized")) {
                $headers.on("click", function () {
                    const $block = $(this)
                        .parent(".footer-col-block")
                        .toggleClass("open");
                    $block.hasClass("open")
                        ? $(this).next().slideDown(250)
                        : $(this).next().slideUp(250);
                });
                $headers.data("accordion-initialized", true);
            } else if (!isMobile()) {
                $headers.off("click").parent().removeClass("open");
                $headers.next().removeAttr("style");
                $headers.data("accordion-initialized", false);
            }
        };

        initAccordion();
        $(window).on("resize", initAccordion);
    };

    /* loadItem
  -------------------------------------------------------------------------------------*/
    const loadItem = () => {
        if (!$("#loadMore").length) return;
        const initialItems = 5,
            itemsPerPage = 2;
        let itemsDisplayed = initialItems;

        const $container = $("#loadMore");
        const $btn = $("#loadMoreBtn");

        const hideExtraItems = () => {
            $container.find(".loadItem").each((i, el) => {
                if (i >= itemsDisplayed) $(el).addClass("hidden");
            });
        };

        const showMoreItems = () => {
            $container
                .find(".loadItem.hidden")
                .slice(0, itemsPerPage)
                .removeClass("hidden");
            if ($container.find(".loadItem.hidden").length === 0) $btn.hide();
            itemsDisplayed += itemsPerPage;
        };

        hideExtraItems();
        $btn.on("click", () => setTimeout(showMoreItems, 600));
    };

    /* changeValue
  -------------------------------------------------------------------------------------*/
    const changeValue = () => {
        if (!$(".tf-dropdown-sort").length) return;
        $(".tf-dropdown-sort .select-item").on("click", function () {
            const $this = $(this);
            const $dropdown = $this.closest(".tf-dropdown-sort");
            $dropdown
                .find(".text-sort-value")
                .text($this.find(".text-value-item").text());
            $dropdown.find(".select-item").removeClass("active");
            $this.addClass("active");
            $dropdown
                .find(".btn-select .current-color")
                .css("background", $this.data("value-color"));
        });
    };

    /* actionMusic
  -------------------------------------------------------------------------------------*/
    const actionMusic = () => {
        if (!$(".box-music").length) return;

        $(document).one("click touchstart keydown", () => {
            if (Howler.ctx && Howler.ctx.state === "suspended") {
                Howler.ctx.resume();
            }
        });

        const players = [];

        $(".box-music").each(function () {
            const $box = $(this);
            let sound = null;

            const getSound = () => {
                if (!sound) {
                    sound = new Howl({
                        src: [$box.data("src")],
                        html5: true,
                        onplay() {
                            players.forEach((p) => p !== sound && p.pause());
                            requestAnimationFrame(update);
                            $box.find(".play-btn").hide();
                            $box.find(".pause-btn").show();
                        },
                        onpause() {
                            $box.find(".play-btn").show();
                            $box.find(".pause-btn").hide();
                        },
                        onend() {
                            $box.find(".play-btn").show();
                            $box.find(".pause-btn").hide();
                            $box.find(".progress").css("width", "0%");
                            $box.find(".time-display").text("00:00");
                        },
                    });
                    players.push(sound);
                }
                return sound;
            };

            function update() {
                if (!sound || !sound.playing()) return;
                const seek = sound.seek() || 0;
                const duration = sound.duration() || 1;

                $box.find(".progress").css(
                    "width",
                    `${(seek / duration) * 100}%`
                );
                const min = String(Math.floor(seek / 60)).padStart(2, "0");
                const sec = String(Math.floor(seek % 60)).padStart(2, "0");
                $box.find(".time-display").text(`${min}:${sec}`);

                if (sound.playing()) requestAnimationFrame(update);
            }

            $box.on("click", ".play-btn", () => {
                const s = getSound();

                if (Howler.ctx && Howler.ctx.state === "suspended") {
                    Howler.ctx.resume().then(() => s.play());
                } else {
                    s.play();
                }
            });

            $box.on("click", ".pause-btn", () => sound && sound.pause());

            $box.on("click", ".prev-btn, .next-btn", () => {
                const s = getSound();
                s.stop();
                s.play();
            });

            $box.on("click", ".progress-bar", function (e) {
                if (!sound) return;
                const percent = e.offsetX / $(this).width();
                sound.seek(sound.duration() * percent);
                update();
            });
        });
    };

    /* handleSidebar
  -------------------------------------------------------------------------------------*/
    const handleSidebar = () => {
        if (!$(".show-sidebar").length) return;
        $(".show-sidebar").on("click", () => {
            if ($(window).width() <= 991) {
                $(".leftBar, .overlay-blog").addClass("show");
                $("body").addClass("no-scroll");
            }
        });

        $(".close-filter, .overlay-blog").on("click", () => {
            $(".leftBar, .overlay-blog").removeClass("show");
            $("body").removeClass("no-scroll");
        });
    };

    /* oneNavOnePage
  -------------------------------------------------------------------------------------*/
    const oneNavOnePage = () => {
        if (!$(".section-onepage").length) return;

        const $navLinks = $(".nav_link");
        const $sections = $(".section");

        $navLinks.on("click", function (e) {
            e.preventDefault();
            const target = $(this).attr("href");
            $("html, body").animate({ scrollTop: $(target).offset().top }, 0);
            $(".leftBar, #overlay-blog").removeClass("show");
            $("body").removeClass("no-scroll");
        });

        const updateActiveMenu = () => {
            const scrollTop = $(window).scrollTop();
            let current = "";
            $sections.each(function () {
                const $section = $(this);
                const top = $section.offset().top - 200;
                const bottom = top + $section.outerHeight();
                if (scrollTop >= top && scrollTop < bottom)
                    current = $section.attr("id");
            });
            $navLinks
                .removeClass("active")
                .filter(`[href="#${current}"]`)
                .addClass("active");
        };

        $(window).on("scroll", updateActiveMenu);
        updateActiveMenu();
    };

    /* handlePopupSearch
  -------------------------------------------------------------------------------------*/
    const handlePopupSearch = () => {
        $(".popup-show-form").each(function () {
            const $popup = $(this);
            const $button = $popup.find(".btn-show");
            const $close = $popup.find(".close-form");
            $button.on("click", function (event) {
                event.preventDefault();
            });
            $button.on("click", () =>
                $popup.find(".popup-show").toggleClass("show")
            );
            $close.on("click", () =>
                $popup.find(".popup-show").removeClass("show")
            );

            $(document).on("click", (e) => {
                if (
                    !$(e.target).closest($popup).length &&
                    !$(e.target).closest($button).length
                ) {
                    $popup.find(".popup-show").removeClass("show");
                }
            });
        });
    };

    /* video
  -------------------------------------------------------------------------------------*/
    const video = () => {
        if (!$(".popup-youtube").length) return;
        $(".popup-youtube").magnificPopup({
            type: "iframe",
        });
    };

    const postProgress = () => {
        if (!$(".post-reading-time__progress").length) return;
        const $wrap = $(".post-reading-time__progress");
        if (!$wrap.length) return;

        const path = $wrap.find(".progress-circle")[0];
        const length = path.getTotalLength();

        path.style.strokeDasharray = `${length} ${length}`;
        path.style.strokeDashoffset = length;

        const $section = $(".section-single-post");
        if (!$section.length) return;

        const updateProgress = () => {
            const sectionTop = $section.offset().top;
            const sectionHeight = $section.outerHeight();
            const scrollY = $(window).scrollTop();

            const scrollable = sectionHeight - $(window).height();
            const scrollInSection = scrollY - sectionTop;

            if (scrollY < sectionTop) {
                path.style.strokeDashoffset = length;
            } else if (scrollInSection > scrollable) {
                path.style.strokeDashoffset = 0;
            } else {
                const progress = scrollInSection / scrollable;
                path.style.strokeDashoffset = length - progress * length;
            }
        };

        updateProgress();
        $(window).on("scroll", updateProgress);
    };

    /* goTop
  -------------------------------------------------------------------------------------*/
    const goTop = () => {
        const $wrap = $(".progress-wrap");
        if (!$wrap.length) return;

        const path = $wrap.find("path")[0];
        const length = path.getTotalLength();

        path.style.strokeDasharray = `${length} ${length}`;
        path.style.strokeDashoffset = length;

        const updateProgress = () => {
            const scroll = $(window).scrollTop();
            const height = $(document).height() - $(window).height();
            path.style.strokeDashoffset = length - (scroll * length) / height;
        };

        const checkVisibility = () => {
            const scroll = $(window).scrollTop();
            const footerTop = $(".footer-go-top").offset().top;
            const winHeight = $(window).height();
            const visible =
                scroll > 200 && scroll + winHeight < footerTop - 350;
            $wrap.toggleClass("active-progress", visible);
        };

        updateProgress();
        $(window).on("scroll", () => {
            updateProgress();
            checkVisibility();
        });

        $(".progress-wrap, .footer-go-top").on("click", function (e) {
            e.preventDefault();
            $("html, body").animate({ scrollTop: 0 }, 0);
        });
    };

    /* scrollTabsX
  -------------------------------------------------------------------------------------*/
    const scrollTabsX = () => {
        if (!$(".scrollContainer").length) return;
        const $slider = $(".scrollContainer");
        if (!$slider.length) return;
        let isDown = false,
            startX = 0,
            scrollLeft = 0;
        $slider.on("mousedown", (e) => {
            isDown = true;
            $slider.css("cursor", "grabbing");
            startX = e.pageX - $slider.offset().left;
            scrollLeft = $slider.scrollLeft();
        });

        $(document).on("mouseup mouseleave", () => {
            isDown = false;
            $slider.css("cursor", "grab");
        });

        $slider.on("mousemove", (e) => {
            if (!isDown) return;
            e.preventDefault();
            const x = e.pageX - $slider.offset().left;
            $slider.scrollLeft(scrollLeft - (x - startX) * 2);
        });
    };

    /* wowAnimation
  -------------------------------------------------------------------------------------*/
    const wowAnimation = () => {
        if (!$(".wow").length) return;
        new WOW({
            boxClass: "wow",
            animateClass: "animated",
            offset: 0,
            mobile: false,
            live: true,
        }).init();
    };

    /* spliting
  -------------------------------------------------------------------------------------*/
    const spliting = () => {
        if ($(".splitting").length) Splitting();
    };

    // Dom Ready
    $(() => {
        headerFixed();
        handleFooter();
        loadItem();
        changeValue();
        actionMusic();
        handleSidebar();
        oneNavOnePage();
        handlePopupSearch();
        video();
        goTop();
        postProgress();
        scrollTabsX();
        wowAnimation();
        spliting();
    });
})(jQuery);
